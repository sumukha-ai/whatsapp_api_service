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
    contacts_by_wa_id = {
        c.get("wa_id"): c.get("profile", {}).get("name")
        for c in value.get("contacts", [])
        if c.get("wa_id")
    }

    for incoming_message in value.get("messages", []):
        from_phone = incoming_message.get("from")
        if not from_phone:
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


def _process_status_updates(value, waba_account_id):
    for status_item in value.get("statuses", []):
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


@webhook_bp.route("/webhook", methods=["POST"])
def whatsapp_webhook_notifcation():
    data = request.get_json(silent=True) or {}
    webhook_log = WebhookLog(payload=data, processed=False)
    db.session.add(webhook_log)
    db.session.commit()

    try:
        logger.info("Incoming webhook payload received")

        for entry in data.get("entry", []):
            entry_waba_id = entry.get("id")
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue

                value = change.get("value", {})
                waba_account_id = _get_waba_account_id(value, entry_waba_id)
                if webhook_log.waba_account_id is None:
                    webhook_log.waba_account_id = waba_account_id

                _process_incoming_messages(value, waba_account_id)
                _process_status_updates(value, waba_account_id)

        webhook_log.processed = True
        webhook_log.processed_at = ist_now()
        db.session.commit()
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
    logger.info("\n\n *************Calling the webhook verify*******************\n\n")
    hub_mode = request.args.get('hub.mode')
    hub_verify_token = request.args.get('hub.verify_token')
    hub_challenge = request.args.get('hub.challenge')
    expected_verify_token = current_app.config.get('WHATSAPP_WEBHOOK_VERIFY_TOKEN')

    if hub_mode == "subscribe" and hub_verify_token == expected_verify_token:
        return str(hub_challenge)
    else:
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
