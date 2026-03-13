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
        
        # Check if this is a message event
        if data.get('entry') and len(data['entry']) > 0:
            entry = data['entry'][0]
            
            if 'changes' in entry:
                for change in entry['changes']:
                    if change.get('field') == 'messages':
                        value = change.get('value', {})
                        
                        # Extract messages from the webhook
                        if 'messages' in value:
                            for message in value['messages']:
                                # Only process button messages with "Apply Now" payload
                                if message.get('type') == 'button':
                                    button_data = message.get('button', {})
                                    payload = button_data.get('payload')
                                    
                                    # Only proceed if the button payload is exactly "Apply Now"
                                    if payload == "Apply Now":
                                        # Process incoming message with context (reply from user)
                                        if 'context' in message:
                                            context = message['context']
                                            message_id = context.get('id')  # The message_id we sent initially
                                            
                                            logger.info(f"Processing 'Apply Now' button click. Original message_id: {message_id}")
                                            
                                            # Look up the original message in whatsapp_messages table
                                            if message_id:
                                                from app import db
                                                from app.models.whatsapp_message import WhatsappMessage
                                                from app.models.job_application import JobApplication
                                                
                                                # Find the original message we sent
                                                original_message = WhatsappMessage.query.filter_by(message_id=message_id).first()
                                                
                                                if original_message:
                                                    user_id = original_message.user_id
                                                    job_id = original_message.job_id
                                                    
                                                    logger.info(f"Found original message. user_id: {user_id}, job_id: {job_id}")
                                                    
                                                    # Get the student_profile_id from user
                                                    from app.models.student_profile import StudentProfile
                                                    student_profile = StudentProfile.query.filter_by(user_id=user_id).first()
                                                    
                                                    if student_profile and job_id:
                                                        # Check if application already exists
                                                        application = JobApplication.query.filter_by(
                                                            student_profile_id=student_profile.id,
                                                            job_id=job_id
                                                        ).first()
                                                        
                                                        if application:
                                                            # Update existing application status to "Applied"
                                                            application.status = "Applied"
                                                            application.last_updated = datetime.utcnow()
                                                            db.session.commit()
                                                            logger.info(f"Updated application status to 'Applied' for student {student_profile.id}, job {job_id}")
                                                            
                                                            # Send success message to user
                                                            _send_success_message(
                                                                to=message.get('from'),
                                                                student_name=student_profile.full_name)
                                                        else:
                                                            # Create new application
                                                            new_application = JobApplication(
                                                                student_profile_id=student_profile.id,
                                                                job_id=job_id,
                                                                status="Applied",
                                                                applied_on=datetime.utcnow()
                                                            )
                                                            db.session.add(new_application)
                                                            db.session.commit()
                                                            logger.info(f"Created new application for student {student_profile.id}, job {job_id}")
                                                            
                                                            # Send success message to user
                                                            _send_success_message(
                                                                to=message.get('from'),
                                                                student_name=student_profile.full_name)
                                                    else:
                                                        logger.warning(f"Could not find student_profile for user_id {user_id}")
                                                else:
                                                    logger.warning(f"Could not find original message with id {message_id} in database")
                                        else:
                                            logger.warning("'Apply Now' message received but no context found")
                                    else:
                                        logger.info(f"Button payload is '{payload}', not 'Apply Now'. Skipping processing.")
                                else:
                                    logger.info(f"Message type is '{message.get('type')}', not 'button'. Skipping processing.")
    
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

    if hub_mode == "subscribe" and hub_verify_token == "Test":
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
