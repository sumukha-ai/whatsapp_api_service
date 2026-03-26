import logging

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.database import db
from app.utils.catch_internal_error import catch_internal_error
from app.models.whatsapp import WabaAccount
from app.utils.meta_api import (
    get_access_token,
    subscribe_to_webhook,
    register_phone
)
from app.config import Config

meta_bp = Blueprint("meta_bp", __name__)

logger = logging.getLogger(__name__)

@meta_bp.route("/embedded_signup", methods=["POST", "OPTIONS"])
@jwt_required()
@catch_internal_error
def embedded_signup():
    if request.method == "OPTIONS":
        return "", 200
    
    data = request.get_json()
    code = data.get("code")
    phone_number_id = data.get("phone_number_id")
    waba_id = data.get("waba_id")
    label = data.get("label") or f"WABA {waba_id}"
    current_user_id = get_jwt_identity()

    if not all([code, phone_number_id, waba_id]):
        return jsonify({"error": "Missing one or more required fields: code, phone_number_id, waba_id"}), 400

    # Step 1: Check existing WhatsApp account details for unique phone_number_id.
    existing_details = WabaAccount.query.filter_by(phone_number_id=phone_number_id).first()

    if existing_details:
        # Keep existing access token and bring the row in sync with payload/user.
        access_token = existing_details.access_token
        existing_details.waba_id = waba_id
        existing_details.user_id = int(current_user_id) if current_user_id is not None else None
        if label:
            existing_details.label = label
        if not existing_details.webhook_verify_token:
            existing_details.webhook_verify_token = Config.WHATSAPP_WEBHOOK_VERIFY_TOKEN
        db.session.commit()
    else:
        # If no record exists, exchange the code for a new token and store all required fields.
        try:
            token_result = get_access_token(code)
            logger.info('code: ', code)
            if not isinstance(token_result, tuple) or len(token_result) != 2:
                raise ValueError(f"Failed to get access token: {token_result}")

            access_token, err = token_result
            logger.info('access_token: ', access_token)
            if err is not None:
                raise ValueError(f"Failed to get access token: {err}")

            whatsapp_details = WabaAccount(
                user_id=int(current_user_id) if current_user_id is not None else None,
                label=label,
                waba_id=waba_id,
                phone_number_id=phone_number_id,
                access_token=access_token,
                webhook_verify_token=Config.WHATSAPP_WEBHOOK_VERIFY_TOKEN
            )
            db.session.add(whatsapp_details)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to exchange code: {str(e)}")
            return jsonify({"error": f"Failed to exchange code"}), 500


    # Step 3: Subscribe to webhook
    try:
        subscribe_to_webhook(
            f"{Config.BACKEND_URL}//webhook",
            Config.WHATSAPP_WEBHOOK_VERIFY_TOKEN,
            waba_id,
            access_token
        )
    except Exception as e:
        logger.error(f"Webhook subscription failed: {str(e)}")
        return jsonify({"error": f"Webhook subscription failed"}), 500

    # Step 4: Register phone number
    try:
        register_phone(phone_number_id, Config.WHATSAPP_REGISTRATION_PIN, access_token)
    except Exception as e:
        logger.error(f"Phone registration failed: {str(e)}")
        return jsonify({"error": f"Phone registration failed"}), 500

    return jsonify({
        "message": "Embedded signup completed successfully",
    }), 200
