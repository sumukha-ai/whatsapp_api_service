"""Celery tasks for WhatsApp group messaging."""
import asyncio
import json
import logging
import os
from app import celery
from app.database import db
from app.models.whatsapp import (
    Contact,
    GroupMessage,
    GroupMessageRecipient,
    WabaAccount,
)
from app.utils.datetime_utils import ist_now

logger = logging.getLogger(__name__)


@celery.task(queue='whatsapp')
def dispatch_group_message(group_message_id, waba_account_id, is_template):
    """Dispatch a group message by splitting recipients into chunks.
    
    Fetches all queued recipients for the given group message,
    splits them into chunks of 200, and dispatches send_chunk tasks.
    
    Args:
        group_message_id: ID of the GroupMessage
        waba_account_id: ID of the WabaAccount
        is_template: Whether the message is a template
    """
    try:
        # Fetch all queued recipients for this group message
        recipients = GroupMessageRecipient.query.filter_by(
            group_message_id=group_message_id,
            status='queued'
        ).order_by(GroupMessageRecipient.id).all()
        
        if not recipients:
            logger.info(f"No queued recipients for group message {group_message_id}")
            return
        
        # Split into chunks of 200
        chunk_size = 200
        for i in range(0, len(recipients), chunk_size):
            chunk = recipients[i:i + chunk_size]
            recipient_ids = [r.id for r in chunk]
            
            # Dispatch send_chunk task
            send_chunk.delay(
                recipient_ids=recipient_ids,
                waba_account_id=waba_account_id,
                is_template=is_template
            )
        
        logger.info(f"Dispatched {len(recipients)} recipients for group message {group_message_id} in chunks of {chunk_size}")
    
    except Exception as e:
        logger.error(f"Error dispatching group message {group_message_id}: {str(e)}", exc_info=True)
        raise


@celery.task(bind=True, queue='whatsapp', max_retries=2)
def send_chunk(self, recipient_ids, waba_account_id, is_template):
    """Send a chunk of messages to multiple recipients.
    
    Args:
        recipient_ids: List of GroupMessageRecipient IDs
        waba_account_id: ID of the WabaAccount
        is_template: Whether the message is a template
    """
    try:
        # Fetch the WABA account
        waba_account = WabaAccount.query.filter_by(id=waba_account_id).first()
        if not waba_account:
            logger.error(f"WABA account {waba_account_id} not found")
            return
        
        # Fetch all recipient records
        recipients = GroupMessageRecipient.query.filter(
            GroupMessageRecipient.id.in_(recipient_ids)
        ).all()
        
        if not recipients:
            logger.info(f"No recipients found for IDs: {recipient_ids}")
            return
        
        # Run async batch send
        asyncio.run(send_batch_async(recipients, waba_account, is_template))
    
    except Exception as exc:
        logger.error(f"Error sending chunk: {str(exc)}", exc_info=True)
        # Retry with countdown of 30 seconds
        raise self.retry(exc=exc, countdown=30)


async def send_batch_async(recipients, waba_account, is_template):
    """Send messages asynchronously to a batch of recipients.
    
    Opens a single AsyncClient and sends all messages concurrently.
    
    Args:
        recipients: List of GroupMessageRecipient objects
        waba_account: WabaAccount instance
        is_template: Whether the message is a template
    """
    import httpx
    
    try:
        async with httpx.AsyncClient() as client:
            # Create tasks for all recipients
            tasks = [
                send_one_async(client, recipient, waba_account, is_template)
                for recipient in recipients
            ]
            
            # Execute all tasks concurrently
            await asyncio.gather(*tasks)
        
        # Commit database changes after all sends complete
        db.session.commit()
        logger.info(f"Successfully sent batch of {len(recipients)} messages")
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in send_batch_async: {str(e)}", exc_info=True)
        raise


async def send_one_async(client, record, waba_account, is_template):
    """Send a single message to one recipient asynchronously.
    
    Args:
        client: httpx.AsyncClient instance
        record: GroupMessageRecipient instance
        waba_account: WabaAccount instance
        is_template: Whether the message is a template
    """
    try:
        # Fetch contact and group message
        contact = Contact.query.filter_by(id=record.contact_id).first()
        group_message = GroupMessage.query.filter_by(id=record.group_message_id).first()
        
        if not contact or not group_message:
            logger.error(f"Contact {record.contact_id} or GroupMessage {record.group_message_id} not found")
            record.status = 'failed'
            record.error_code = 'NOT_FOUND'
            record.error_text = 'Contact or GroupMessage not found'
            record.failed_at = ist_now()
            return
        
        # Build Meta API payload
        if is_template:
            payload = {
                'messaging_product': 'whatsapp',
                'to': contact.phone_number,
                'type': 'template',
                'template': group_message.template_payload,
            }
        else:
            payload = {
                'messaging_product': 'whatsapp',
                'to': contact.phone_number,
                'type': 'text',
                'text': {
                    'body': group_message.body
                },
            }
        
        # Prepare request
        base_url = os.getenv('GRAPH_URL_BASE', 'https://graph.facebook.com')
        url_version = os.getenv('GRAPH_URL_VERSION', 'v22.0')
        url = f"{base_url}/{url_version}/{waba_account.phone_number_id}/messages"
        # url = f"http://localhost:5000/dummy"  # For testing with mock API
        
        headers = {
            'Authorization': f'Bearer {waba_account.access_token}',
            'Content-Type': 'application/json',
        }
        
        # Convert template to JSON string if needed
        if is_template:
            payload['template'] = json.dumps(payload.get('template', {}))
        else:
            payload['text'] = json.dumps(payload.get('text', {}))
        
        # Send request
        response = await client.post(url, json=payload, headers=headers, timeout=20)
        
        logger.info(f"Response for {contact.phone_number}: {response.status_code}")
        
        # Update record based on response
        if response.status_code in (200, 201, 202):
            try:
                response_json = response.json()
                provider_message_id = response_json.get('messages', [{}])[0].get('id')
                record.provider_message_id = provider_message_id
                record.status = 'sent'
                record.sent_at = ist_now()
            except Exception as e:
                logger.error(f"Error parsing response for {contact.phone_number}: {str(e)}")
                record.status = 'failed'
                record.error_code = 'PARSE_ERROR'
                record.error_text = str(e)
                record.failed_at = ist_now()
        else:
            record.status = 'failed'
            record.error_code = str(response.status_code)
            record.error_text = response.text
            record.failed_at = ist_now()
            logger.error(f"Failed to send to {contact.phone_number}: {response.text}")
    
    except Exception as e:
        logger.error(f"Exception while sending to {record.contact_id}: {str(e)}", exc_info=True)
        record.status = 'failed'
        record.error_code = 'EXCEPTION'
        record.error_text = str(e)
        record.failed_at = ist_now()
