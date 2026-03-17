import logging
from urllib.parse import quote

import requests
from flask import Blueprint, jsonify, request, current_app
from app.models.whatsapp import WabaAccount, Template  # adjust path to match your project structure
from app.models import db
from app.utils.protected_routes import token_required


templates_bp = Blueprint('templates', __name__)
logger = logging.getLogger(__name__)


class WhatsAppApiError(Exception):
    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get_waba_account(decoded):
    """Fetch the WabaAccount for the authenticated user."""
    return WabaAccount.query.filter(WabaAccount.user_id == decoded["sub"]).one()


def get_headers(waba_account):
    """Build auth headers using the per-account access token."""
    return {'Authorization': f'Bearer {waba_account.access_token}'}


def get_base_url():
    base_url = current_app.config.get('GRAPH_URL_BASE', 'https://graph.facebook.com')
    url_version = current_app.config.get('GRAPH_URL_VERSION', 'v22.0')
    return f"{base_url}/{url_version}"


def validate_template_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid template structure")

    if not payload.get("name"):
        raise ValueError("Template name is required")

    required_fields = ["language", "category", "components"]
    if any(not payload.get(field) for field in required_fields):
        raise ValueError("Invalid template structure")

    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("Invalid template structure")

    for component in components:
        if not isinstance(component, dict) or not component.get("type"):
            raise ValueError("Invalid template structure")


def normalize_template(template_data, default_id=None):
    return {
        "id": template_data.get("id") or default_id,
        "name": template_data.get("name"),
        "category": template_data.get("category"),
        "language": template_data.get("language"),
        "components": template_data.get("components") or [],
    }


def _is_pending_status(status):
    normalized = (status or '').strip().upper()
    return normalized in {'PENDING', 'PENDING_APPROVAL'}


def _refresh_pending_template_statuses(waba_account, local_templates):
    """Refresh only pending local template statuses from WhatsApp and persist changes."""
    pending_templates = [t for t in local_templates if _is_pending_status(t.status)]
    if not pending_templates:
        return

    has_updates = False
    for template in pending_templates:
        encoded_name = quote((template.template_name or '').strip(), safe='')
        endpoint = f"{waba_account.waba_id}/message_templates?name={encoded_name}"
        response_data = make_request_with_headers("GET", endpoint, waba_account)
        wa_templates = response_data.get("data", []) if isinstance(response_data, dict) else []

        normalized_language = (template.language or '').strip().lower()
        matching_template = next(
            (
                wa_template for wa_template in wa_templates
                if isinstance(wa_template, dict)
                and (wa_template.get('language') or '').strip().lower() == normalized_language
            ),
            None
        )

        if not matching_template and wa_templates:
            first_item = wa_templates[0]
            matching_template = first_item if isinstance(first_item, dict) else None

        wa_status = matching_template.get('status') if matching_template else None
        if not wa_status:
            continue
        if (template.status or '') != wa_status:
            template.status = wa_status
            has_updates = True

    if has_updates:
        db.session.commit()


def extract_template_fields(payload):
    """Extract header, body, footer, and buttons from template components."""
    header_type = None
    header_content = None
    body_text = ""
    footer_text = None
    buttons = None
    
    components = payload.get("components", [])
    for component in components:
        comp_type = component.get("type", "").upper()
        
        if comp_type == "HEADER":
            header_type = component.get("format", "TEXT").upper()
            if header_type == "TEXT":
                header_content = component.get("text")
            else:
                header_content = component.get("example", {}).get("header_handle", [None])[0] if component.get("example") else None
        
        elif comp_type == "BODY":
            body_text = component.get("text", "")
        
        elif comp_type == "FOOTER":
            footer_text = component.get("text")
        
        elif comp_type == "BUTTONS":
            buttons = component.get("buttons", [])
    
    return header_type, header_content, body_text, footer_text, buttons


def make_request_with_headers(method, endpoint, waba_account, data=None):
    """Make an authenticated request to the WhatsApp Graph API."""
    try:
        headers = get_headers(waba_account)
        url = f"{get_base_url()}/{endpoint}"

        response = requests.request(method, url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred: {http_err}\n{response.text}")
        error_payload = {}

        try:
            error_payload = response.json().get("error", {})
        except Exception:
            error_payload = {}

        message = (
            error_payload.get("error_user_msg")
            or error_payload.get("message")
            or "Request to WhatsApp API failed"
        )
        raise WhatsAppApiError(message, status_code=response.status_code)
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Request error occurred: {req_err}")
        raise WhatsAppApiError("Failed to reach WhatsApp API", status_code=502)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise WhatsAppApiError("An unexpected error occurred.", status_code=500)


@templates_bp.route('', methods=['POST'])
@token_required
def create_template(decoded):
    try:
        waba_account = get_waba_account(decoded)
        endpoint = f"{waba_account.waba_id}/message_templates"
        payload = request.get_json(silent=True) or {}
        validate_template_payload(payload)

        created = make_request_with_headers("POST", endpoint, waba_account, payload)
        
        # Extract template fields from components
        header_type, header_content, body_text, footer_text, buttons = extract_template_fields(payload)
        
        # Save template to local database
        template = Template(
            waba_id=waba_account.waba_id,
            waba_account_id=waba_account.id,
            template_name=payload.get("name"),
            category=payload.get("category"),
            language=payload.get("language"),
            status=created.get("status", "pending_approval"),
            header_type=header_type,
            header_content=header_content,
            body_text=body_text,
            footer_text=footer_text,
            buttons=buttons,
        )
        db.session.add(template)
        db.session.commit()
        
        return jsonify({
            "id": template.id,
            "name": template.template_name,
            "status": template.status,
        }), 201

    except ValueError as ve:
        return jsonify({'message': str(ve)}), 400
    except WhatsAppApiError as wae:
        return jsonify({'message': wae.message}), wae.status_code
    except Exception as e:
        logger.error(f"Error while creating the template: {e}")
        db.session.rollback()
        return jsonify({'message': 'Unable to create template'}), 500


@templates_bp.route('/<template_id>', methods=['PUT'])
@token_required
def edit_template(decoded, template_id):
    try:
        waba_account = get_waba_account(decoded)
        payload = request.get_json(silent=True) or {}
        validate_template_payload(payload)

        make_request_with_headers("POST", template_id, waba_account, payload)
        return jsonify({
            "id": template_id,
            "name": payload.get("name"),
            "status": "updated",
        }), 200

    except ValueError as ve:
        return jsonify({'message': str(ve)}), 400
    except WhatsAppApiError as wae:
        if wae.status_code == 404:
            return jsonify({'message': 'Template not found'}), 404
        return jsonify({'message': 'Failed to update template'}), 500
    except Exception as e:
        logger.error(f"Error while editing template ID {template_id}: {e}")
        return jsonify({'message': 'Failed to update template'}), 500


@templates_bp.route('/', methods=['GET'])
@token_required
def get_all_local_templates(decoded):
    """
    Replaces get_all_pre_approved_templates.
    Returns templates stored locally in the Template table for this WABA account.
    """
    try:
        waba_account = get_waba_account(decoded)
        templates = Template.query.filter_by(waba_account_id=waba_account.id).all()

        _refresh_pending_template_statuses(waba_account, templates)

        result = [
            {
                'id': t.id,
                'waba_id': t.waba_id,
                'template_name': t.template_name,
                'category': t.category,
                'language': t.language,
                'status': t.status,
                'header_type': t.header_type,
                'header_content': t.header_content,
                'body_text': t.body_text,
                'footer_text': t.footer_text,
                'buttons': t.buttons,
            }
            for t in templates
        ]

        return jsonify({"data": result})

    except ValueError as ve:
        return jsonify({'message': 'Unable to fetch local templates', 'errors': str(ve)}), 400
    except WhatsAppApiError as wae:
        db.session.rollback()
        return jsonify({'message': wae.message}), wae.status_code
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error while fetching local templates: {e}")
        return jsonify({'message': 'Unable to fetch local templates'}), 500


@templates_bp.route('/wa', methods=['GET'])
@token_required
def get_all_templates(decoded):
    try:
        waba_account = get_waba_account(decoded)
        endpoint = f"{waba_account.waba_id}/message_templates?limit=100"

        response_data = make_request_with_headers("GET", endpoint, waba_account)
        data = response_data.get("data", []) if isinstance(response_data, dict) else []
        templates = [normalize_template(item) for item in data if isinstance(item, dict)]
        return jsonify(templates), 200

    except WhatsAppApiError as wae:
        return jsonify({'message': wae.message}), wae.status_code
    except Exception as e:
        logger.error(f"Error while fetching templates: {e}")
        return jsonify({'message': 'Unable to fetch templates'}), 500


@templates_bp.route('/<template_id>', methods=['GET'])
@token_required
def get_template_by_id(decoded, template_id):
    try:
        waba_account = get_waba_account(decoded)
        response_data = make_request_with_headers("GET", template_id, waba_account)
        template = normalize_template(response_data, default_id=template_id)

        if not template.get("id"):
            return jsonify({'message': 'Template not found'}), 404

        return jsonify({"template": template}), 200

    except WhatsAppApiError as wae:
        if wae.status_code == 404:
            return jsonify({'message': 'Template not found'}), 404
        return jsonify({'message': wae.message}), wae.status_code
    except Exception as e:
        logger.error(f"Error fetching template by ID {template_id}: {e}")
        return jsonify({'message': 'Unable to fetch template by ID'}), 500
