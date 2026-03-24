import logging
import json
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort, current_app

from app.database import db
from app.models.whatsapp import (
    Contact,
    Conversation,
    GroupMessageRecipient,
    Message,
    Template,
    WabaAccount,
    WebhookLog,
)
from app.utils.datetime_utils import ist_from_unix, ist_now

webhook_bp = Blueprint("webhook_bp", __name__)

logger = logging.getLogger(__name__)

CONVERSATION_WINDOW_HOURS = 24


def _parse_unix_timestamp(timestamp_value):
    if timestamp_value is None:
        return None

    try:
        return ist_from_unix(timestamp_value)
    except (TypeError, ValueError):
        logger.warning("Unable to parse timestamp: %s", timestamp_value)
        return None


def _json_for_log(payload):
    try:
        return json.dumps(payload, default=str)
    except Exception:
        return str(payload)


def _extract_message_body(message):
    message_type = message.get("type", "text")

    if message_type == "text":
        return message.get("text", {}).get("body")

    if message_type == "button":
        return message.get("button", {}).get("text")

    if message_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")

        if interactive_type == "button_reply":
            return interactive.get("button_reply", {}).get("title")
        if interactive_type == "list_reply":
            return interactive.get("list_reply", {}).get("title")

        return json.dumps(interactive)

    if message_type == "template":
        template_data = message.get("template", {})
        return template_data.get("name") or json.dumps(template_data)

    payload = message.get(message_type, {})
    if isinstance(payload, dict):
        if payload.get("caption"):
            return payload["caption"]
        return json.dumps(payload)

    if payload is None:
        return None

    return str(payload)


def _get_or_create_contact(phone_number, name, waba_account_id=None):
    contact = Contact.query.filter_by(phone_number=phone_number).one_or_none()

    # Use phone number as fallback name if not provided
    contact_name = name or phone_number

    if contact is None:
        contact = Contact(
            phone_number=phone_number,
            name=contact_name,
            waba_account_id=waba_account_id,
        )
        db.session.add(contact)
        db.session.flush()
    else:
        if contact_name and contact.name != contact_name:
            contact.name = contact_name
        if waba_account_id and contact.waba_account_id != waba_account_id:
            contact.waba_account_id = waba_account_id

    return contact


def _window_expires_at(start_time):
    return start_time + timedelta(hours=CONVERSATION_WINDOW_HOURS)


def _ensure_window_fields(conversation):
    if conversation is None:
        return None

    if conversation.created_at and conversation.session_expires_at is None:
        conversation.session_expires_at = _window_expires_at(conversation.created_at)

    return conversation


def _close_if_expired(conversation, reference_time=None):
    if conversation is None:
        return None

    _ensure_window_fields(conversation)
    reference_time = reference_time or ist_now()

    if conversation.session_expires_at and conversation.session_expires_at <= reference_time:
        conversation.status = "closed"

    return conversation


def _get_active_conversation(contact_id, waba_account_id=None, reference_time=None):
    conversation = (
        Conversation.query
        .filter_by(contact_id=contact_id, waba_account_id=waba_account_id, status="open")
        .order_by(Conversation.created_at.desc())
        .first()
    )
    conversation = _close_if_expired(conversation, reference_time)
    if conversation and conversation.status == "closed":
        return None
    return conversation


def _create_conversation(contact_id, waba_account_id=None, start_time=None):
    start_time = start_time or ist_now()
    conversation = Conversation(
        contact_id=contact_id,
        waba_account_id=waba_account_id,
        status="open",
        created_at=start_time,
        updated_at=start_time,
        session_expires_at=_window_expires_at(start_time),
    )
    db.session.add(conversation)
    db.session.flush()
    return conversation


def _apply_template_timer(conversation, session_expires_at):
    if conversation is None:
        return

    conversation.session_expires_at = session_expires_at

    if session_expires_at and session_expires_at <= ist_now():
        conversation.status = "closed"
    else:
        conversation.status = "open"


def _get_waba_account_id(value, entry_waba_id):
    metadata = value.get("metadata", {})
    phone_number_id = metadata.get("phone_number_id")

    if phone_number_id:
        account = WabaAccount.query.filter_by(phone_number_id=phone_number_id).one_or_none()
        if account:
            return account.id

    if entry_waba_id:
        account = WabaAccount.query.filter_by(waba_id=entry_waba_id).one_or_none()
        if account:
            return account.id

    return None


def _process_incoming_messages(value, waba_account_id):
    logger.info(
        "Processing incoming messages: waba_account_id=%s contacts=%s messages=%s",
        waba_account_id,
        len(value.get("contacts", [])),
        len(value.get("messages", [])),
    )

    contacts_by_wa_id = {
        c.get("wa_id"): c.get("profile", {}).get("name")
        for c in value.get("contacts", [])
        if c.get("wa_id")
    }

    for incoming_message in value.get("messages", []):
        logger.info("Incoming message event: %s", _json_for_log(incoming_message))

        from_phone = incoming_message.get("from")
        if not from_phone:
            logger.warning("Incoming message skipped because sender is missing: %s", _json_for_log(incoming_message))
            continue

        contact_name = contacts_by_wa_id.get(from_phone)
        contact = _get_or_create_contact(from_phone, contact_name, waba_account_id)

        received_at = _parse_unix_timestamp(incoming_message.get("timestamp")) or ist_now()
        conversation = _get_active_conversation(contact.id, waba_account_id, reference_time=received_at)

        if conversation is None:
            conversation = _create_conversation(contact.id, waba_account_id, start_time=received_at)

        wamid = incoming_message.get("id")
        message_record = Message.query.filter_by(wamid=wamid).one_or_none() if wamid else None
        if message_record is None:
            message_record = Message(
                waba_account_id=waba_account_id,
                conversation_id=conversation.id,
                contact_id=contact.id,
                wamid=wamid,
                direction="inbound",
                type=incoming_message.get("type", "unknown"),
            )
            db.session.add(message_record)

        message_record.body = _extract_message_body(incoming_message)
        message_record.status = "received"
        message_record.sent_at = received_at

        logger.info(
            "Inbound message processed: wamid=%s contact_id=%s conversation_id=%s status=%s type=%s",
            message_record.wamid,
            message_record.contact_id,
            message_record.conversation_id,
            message_record.status,
            message_record.type,
        )


def _process_status_updates(value, waba_account_id):
    logger.info(
        "Processing status updates: waba_account_id=%s statuses=%s",
        waba_account_id,
        len(value.get("statuses", [])),
    )

    for status_item in value.get("statuses", []):
        logger.info("Status event: %s", _json_for_log(status_item))

        wamid = status_item.get("id")
        status_value = status_item.get("status")
        status_timestamp = _parse_unix_timestamp(status_item.get("timestamp"))
        recipient_id = status_item.get("recipient_id")

        message_record = Message.query.filter_by(wamid=wamid).one_or_none() if wamid else None

        contact = None
        conversation = None
        if message_record is None and recipient_id:
            contact = _get_or_create_contact(recipient_id, None, waba_account_id)
            reference_time = status_timestamp or ist_now()
            conversation = _get_active_conversation(contact.id, waba_account_id, reference_time=reference_time)
            if conversation is None:
                conversation = _create_conversation(contact.id, waba_account_id, start_time=reference_time)

            conversation_info = status_item.get("conversation", {})
            expiration_timestamp = _parse_unix_timestamp(conversation_info.get("expiration_timestamp"))
            if expiration_timestamp:
                _apply_template_timer(conversation, expiration_timestamp)

            message_record = Message(
                waba_account_id=waba_account_id,
                conversation_id=conversation.id,
                contact_id=contact.id,
                wamid=wamid,
                direction="outbound",
                type="template",
            )
            db.session.add(message_record)

        if message_record is None:
            logger.warning(
                "Status event skipped because no message record could be resolved: wamid=%s recipient_id=%s status=%s",
                wamid,
                recipient_id,
                status_value,
            )
            continue

        if conversation is None:
            conversation = Conversation.query.get(message_record.conversation_id)
            conversation = _close_if_expired(conversation, status_timestamp or ist_now())

        conversation_info = status_item.get("conversation", {})
        expiration_timestamp = _parse_unix_timestamp(conversation_info.get("expiration_timestamp"))
        if expiration_timestamp:
            _apply_template_timer(conversation, expiration_timestamp)

        if status_value:
            message_record.status = status_value

        if status_value == "sent":
            message_record.sent_at = status_timestamp or message_record.sent_at
        elif status_value == "delivered":
            message_record.delivered_at = status_timestamp or message_record.delivered_at
        elif status_value == "read":
            message_record.read_at = status_timestamp or message_record.read_at

        logger.info(
            "Message status updated: wamid=%s status=%s sent_at=%s delivered_at=%s read_at=%s",
            message_record.wamid,
            message_record.status,
            message_record.sent_at,
            message_record.delivered_at,
            message_record.read_at,
        )

        recipient_record = GroupMessageRecipient.query.filter_by(provider_message_id=wamid).one_or_none() if wamid else None
        if recipient_record is None:
            continue

        if status_value:
            recipient_record.status = status_value

        if status_value == "sent":
            recipient_record.sent_at = status_timestamp or recipient_record.sent_at
        elif status_value == "delivered":
            recipient_record.delivered_at = status_timestamp or recipient_record.delivered_at
        elif status_value == "read":
            recipient_record.read_at = status_timestamp or recipient_record.read_at
        elif status_value == "failed":
            recipient_record.failed_at = status_timestamp or ist_now()
            errors = status_item.get("errors", [])
            if errors:
                first_error = errors[0]
                recipient_record.error_code = str(first_error.get("code") or first_error.get("title") or "WA_SEND_FAILED")
                recipient_record.error_text = first_error.get("details") or first_error.get("title")

        logger.info(
            "Group recipient status updated: provider_message_id=%s status=%s sent_at=%s delivered_at=%s read_at=%s failed_at=%s",
            recipient_record.provider_message_id,
            recipient_record.status,
            recipient_record.sent_at,
            recipient_record.delivered_at,
            recipient_record.read_at,
            recipient_record.failed_at,
        )


def _normalize_template_status(status):
    return (status or '').strip().upper() or None


def _process_template_status_update(value, entry_waba_id=None):
    """Update local template status from template-status webhook payloads."""
    if not isinstance(value, dict):
        return False

    logger.info(
        "Checking template status event: entry_waba_id=%s payload=%s",
        entry_waba_id,
        _json_for_log(value),
    )

    template_status = _normalize_template_status(
        value.get('message_template_status')
        or value.get('status')
        or value.get('event')
    )
    if not template_status:
        return False

    template_meta_id = value.get('message_template_id') or value.get('template_id')
    template_name = value.get('message_template_name') or value.get('name')

    query = Template.query
    if entry_waba_id:
        query = query.filter(Template.waba_id == entry_waba_id)

    if template_meta_id:
        query = query.filter(Template.meta_template_id == str(template_meta_id))
    elif template_name:
        query = query.filter(Template.template_name == str(template_name))
    else:
        return False

    templates = query.all()
    if not templates:
        logger.info(
            "Template status update received but no template matched: entry_waba_id=%s template_meta_id=%s template_name=%s status=%s",
            entry_waba_id,
            template_meta_id,
            template_name,
            template_status,
        )
        return False

    for template in templates:
        template.status = template_status

    logger.info(
        "Template status updated: entry_waba_id=%s matched_templates=%s template_meta_id=%s template_name=%s status=%s",
        entry_waba_id,
        len(templates),
        template_meta_id,
        template_name,
        template_status,
    )

    return True


@webhook_bp.route("/webhook", methods=["POST"])
def whatsapp_webhook_notifcation():
    data = request.get_json(silent=True) or {}
    logger.info("Webhook POST received: %s", _json_for_log(data))

    webhook_log = WebhookLog(payload=data, processed=False)
    db.session.add(webhook_log)
    db.session.commit()

    try:
        logger.info("Incoming webhook payload persisted in webhook_log id=%s", webhook_log.id)
        has_template_status_updates = _process_template_status_update(data)

        for entry in data.get("entry", []):
            entry_waba_id = entry.get("id")
            logger.info("Processing entry: waba_id=%s entry=%s", entry_waba_id, _json_for_log(entry))

            for change in entry.get("changes", []):
                logger.info("Processing change: field=%s change=%s", change.get("field"), _json_for_log(change))

                value = change.get("value", {})
                if _process_template_status_update(value, entry_waba_id):
                    has_template_status_updates = True
                    continue

                if change.get("field") != "messages":
                    logger.info(
                        "Skipping unsupported change field: field=%s value=%s",
                        change.get("field"),
                        _json_for_log(value),
                    )
                    continue

                waba_account_id = _get_waba_account_id(value, entry_waba_id)
                logger.info(
                    "Resolved WABA account for message change: entry_waba_id=%s waba_account_id=%s",
                    entry_waba_id,
                    waba_account_id,
                )
                if webhook_log.waba_account_id is None:
                    webhook_log.waba_account_id = waba_account_id

                _process_incoming_messages(value, waba_account_id)
                _process_status_updates(value, waba_account_id)

        if has_template_status_updates:
            logger.info('Processed message template status updates from webhook payload')

        webhook_log.processed = True
        webhook_log.processed_at = ist_now()
        db.session.commit()
        logger.info("Webhook processing completed successfully for webhook_log id=%s", webhook_log.id)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        resp = jsonify(success=False, message="Webhook processing failed")
        resp.status_code = 200
        return resp
    
    resp = jsonify(success=True)
    resp.status_code = 200
    return resp


@webhook_bp.route("/webhook", methods=["GET"])
def whatsapp_webhook():
    logger.info("Calling webhook verification endpoint")
    hub_mode = request.args.get('hub.mode')
    hub_verify_token = request.args.get('hub.verify_token')
    hub_challenge = request.args.get('hub.challenge')
    expected_verify_token = current_app.config.get('WHATSAPP_WEBHOOK_VERIFY_TOKEN')

    logger.info(
        "Webhook verify request params: hub.mode=%s hub.verify_token_present=%s hub.challenge_present=%s",
        hub_mode,
        bool(hub_verify_token),
        bool(hub_challenge),
    )

    if hub_mode == "subscribe" and hub_verify_token == expected_verify_token:
        logger.info("Webhook verification successful")
        return str(hub_challenge)
    else:
        logger.warning("Webhook verification failed")
        abort(401)


def _send_success_message(to: str, student_name: str):
    """
    Send a success message to the student via WhatsApp after they apply to a job.
    
    Args:
        to (str): Recipient's phone number
        student_name (str): Student's name for personalization
        job_title (str): Job title they applied for
    """
    try:
        from app.services.whatsapp_service import send_whatsapp_text_message
        
        # Craft a personalized success message
        success_message = f"✅ Great! Your application has been received successfully, {student_name}! "
        
        # Send success message via WhatsApp text
        response = send_whatsapp_text_message(to=to, message_body=success_message)
        
        if response.get("status") == "success":
            logger.info(f"Success message sent to {to}")
        else:
            logger.warning(f"Failed to send success message to {to}: {response.get('message')}")
    
    except Exception as e:
        logger.error(f"Error sending success message to {to}: {str(e)}", exc_info=True)
