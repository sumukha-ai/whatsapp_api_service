import logging

from flask import Blueprint, request, jsonify, abort
from datetime import datetime

webhook_bp = Blueprint("webhook_bp", __name__)

logger = logging.getLogger("__name__")


@webhook_bp.route("/webhook", methods=["POST"])
def whatsapp_webhook_notifcation():
    logger.info("\n\n\n\n*************")
    logger.info(type(request.json))
    logger.info(request.json)
    logger.info("*************\n\n\n\n")
    
    try:
        # Extract the webhook payload
        data = request.json
        logger.info('data: %s', data)
                                      
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
    
    resp = jsonify(success=True)
    resp.status_code = 200
    return resp


@webhook_bp.route("/webhook", methods=["GET"])
def whatsapp_webhook():
    logger.info("\n\n *************Calling the webhook verify*******************\n\n")
    hub_mode = request.args.get('hub.mode')
    hub_verify_token = request.args.get('hub.verify_token')
    hub_challenge = request.args.get('hub.challenge')

    if hub_mode == "subscribe" and hub_verify_token == "thisIsASuperSecretToken":
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
