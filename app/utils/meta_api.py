import logging

import requests
import os
from dotenv import load_dotenv
import json

# Optional: Load from .env in development
load_dotenv()

logger = logging.getLogger(__name__)


def get_access_token(code: str):
    """
    Exchanges an authorization code for an access token using Facebook Graph API.

    Args:
        code (str): The authorization code received from the OAuth flow.

    Returns:
        dict: JSON response from Facebook or error details.
    """
    if not code:
        return {"error": "Missing 'code' parameter"}

    # Get environment variables
    client_id = os.getenv('CLIENT_ID')
    client_secret = os.getenv('CLIENT_SECRET')
    grant_type = os.getenv('GRANT_TYPE', 'authorization_code')  # Default value

    if not client_id or not client_secret:
        return {"error": "CLIENT_ID or CLIENT_SECRET environment variable not set"}

    # Facebook OAuth URL
    url = "https://graph.facebook.com/v22.0/oauth/access_token"
    params = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': code,
        'grant_type': grant_type
    }

    headers = {
        'Content-Type': 'application/json'
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        return response.json()["access_token"], None
    except requests.exceptions.RequestException as e:
        return {
            "error": str(e),
            "details": e.response.json() if e.response else None
        }


def subscribe_to_webhook(callback_uri, verify_token, waba_id, access_token):
    """
    Subscribes an app to webhook notifications with dynamic parameters.

    Args:
        callback_uri (str): The public URL of your webhook endpoint.
        verify_token (str): The secret token to verify webhook setup.
        app_id (str): The Facebook App ID to subscribe.
        access_token (str): The App Access Token for authorization.

    Returns:
        A tuple containing the HTTP status code and the JSON response from the server.
    """

    # The target URL is constructed using the app_id
    url = f'https://graph.facebook.com/v20.0/{waba_id}/subscribed_apps'

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'

    }

    # The JSON data payload now uses the function parameters
    payload = json.dumps({
        "override_callback_uri": callback_uri,
        "verify_token": verify_token
    })

    try:
        # Make the POST request
        logger.info("Calling the subscribe webhook API")
        response = requests.post(url, headers=headers, data=payload)
        logger.info(f"Subscribe webhook API response: {response.json()}")
        response.raise_for_status()  # Raise an exception for bad status codes

        # Return the status code and the JSON response
        return response.status_code, response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"An error occurred while subscribing to webhook: {e}")
        if e.response:
            logger.error(f"Response Body: {e.response.text}")
        return None, None


def register_phone(phone_number_id, pin, access_token):
    """
    Registers a WhatsApp Business phone number by verifying it with a PIN.

    This function replicates the curl command to finalize the phone number
    registration process.

    Args:
        phone_number_id (str): The ID of the phone number to register.
        pin (str): The 6-digit PIN received via SMS or voice call.
        access_token (str): The access token for authorization.

    Returns:
        A tuple containing the HTTP status code and the JSON response from the server.
        Returns (None, None) if a request-related error occurs.
    """
    # The target URL is constructed using the phone_number_id
    logger.info(f"Registering the business phone with ID: {phone_number_id}")
    url = f'https://graph.facebook.com/v20.0/{phone_number_id}/register'

    # The headers, including the dynamic access token
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }

    # The JSON data payload with the messaging product and PIN
    payload = {
        "messaging_product": "whatsapp",
        "pin": pin
    }

    try:
        # Make the POST request
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()  # Raise an exception for HTTP errors

        # Return the status code and the JSON response
        return response.status_code, response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"An error occurred while registering phone: {e}")
        if e.response:
            logger.error(f"Response Body: {e.response.text}")
        return None, None
