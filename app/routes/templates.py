import logging
import os
import re
import json
from urllib.parse import quote

import requests
from flask import Blueprint, jsonify, request, current_app
from app.models.whatsapp import WabaAccount, Template
from app.models import db
from app.utils.protected_routes import token_required


templates_bp = Blueprint('templates', __name__)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


ALLOWED_IMAGE_MIME_TYPES = {'image/jpeg', 'image/png'}
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024


class WhatsAppApiError(Exception):
    def __init__(self, message, status_code=500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _payload_log_summary(payload):
    """Return a compact payload summary without logging full raw input JSON."""
    if not isinstance(payload, dict):
        return {'payload_type': str(type(payload))}

    components = payload.get('components') or []
    component_types = []
    image_header_present = False
    has_header_handle = False

    for component in components:
        if not isinstance(component, dict):
            continue
        comp_type = (component.get('type') or '').upper()
        component_types.append(comp_type)
        if comp_type == 'HEADER' and (component.get('format') or '').upper() == 'IMAGE':
            image_header_present = True
            existing = _get_existing_header_handle(component)
            if existing:
                has_header_handle = True

    return {
        'name': payload.get('name'),
        'language': payload.get('language'),
        'category': payload.get('category'),
        'component_count': len(components) if isinstance(components, list) else 0,
        'component_types': component_types,
        'image_header_present': image_header_present,
        'has_existing_header_handle': has_header_handle,
    }


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

    template_name = (payload.get("name") or '').strip()
    if not template_name:
        raise ValueError("Template name is required")

    _validate_template_name(template_name)

    required_fields = ["language", "category", "components"]
    if any(not payload.get(field) for field in required_fields):
        raise ValueError("Invalid template structure")

    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("Invalid template structure")

    for component in components:
        if not isinstance(component, dict) or not component.get("type"):
            raise ValueError("Invalid template structure")


def _validate_template_name(template_name):
    if not re.fullmatch(r'[a-z0-9_]+', template_name or ''):
        raise ValueError('Template name must be lowercase and may only contain letters, numbers, and underscores')


def _extract_image_header_component(payload):
    components = payload.get('components', []) if isinstance(payload, dict) else []
    for component in components:
        if not isinstance(component, dict):
            continue
        if (component.get('type') or '').upper() != 'HEADER':
            continue
        if (component.get('format') or '').upper() == 'IMAGE':
            return component
    return None


def _get_existing_header_handle(header_component):
    if not isinstance(header_component, dict):
        return None
    example = header_component.get('example') or {}
    handles = example.get('header_handle') if isinstance(example, dict) else None
    if isinstance(handles, list) and handles:
        return handles[0]
    return None


def _validate_sample_image(sample_image):
    if not sample_image:
        raise ValueError('sample_image file is required for IMAGE header templates')

    filename = os.path.basename((sample_image.filename or '').strip())
    if not filename:
        raise ValueError('sample_image filename is required')
    extension = os.path.splitext(filename)[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError('Allowed image types are JPG and PNG only')

    mime_type = (sample_image.mimetype or '').lower()
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError('Allowed MIME types are image/jpeg and image/png only')

    # Validate size directly from stream; do not trust client metadata.
    sample_image.stream.seek(0, os.SEEK_END)
    file_size = sample_image.stream.tell()
    sample_image.stream.seek(0)
    if file_size > MAX_IMAGE_SIZE_BYTES:
        raise ValueError('Image file size must be 5 MB or smaller')

    return filename, mime_type, file_size


def _parse_template_creation_request():
    if request.is_json:
        return request.get_json(silent=True) or {}, None

    payload_raw = request.form.get('payload') or request.form.get('template')
    if not payload_raw:
        raise ValueError('Missing template payload')

    try:
        payload = json.loads(payload_raw)
    except (TypeError, ValueError):
        raise ValueError('Invalid JSON in payload')

    sample_image = request.files.get('sample_image') or request.files.get('file')
    return payload, sample_image


def _create_graph_upload_session(waba_account, file_name, file_length, file_type):
    """
    Step 1 of Meta Resumable Upload:
    POST /{app-id}/uploads → returns upload session ID like "upload:MTp..."
    """
    app_id = current_app.config.get('META_APP_ID') or current_app.config.get('META_CLIENT_ID')
    if not app_id:
        raise WhatsAppApiError('META_APP_ID (or META_CLIENT_ID) is not configured', status_code=500)

    url = f"{get_base_url()}/{app_id}/uploads"
    payload = {
        'file_name': file_name,
        'file_length': str(file_length),
        'file_type': file_type,
        'access_token': waba_account.access_token,
    }

    try:
        logger.error(
            'Step 1 request: app_id=%s waba_id=%s file_name=%s file_length=%s file_type=%s',
            app_id,
            waba_account.waba_id,
            file_name,
            file_length,
            file_type,
        )
        response = requests.post(url, data=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        logger.info("***************************************************")
        logger.info('step 1: Upload session creation')
        log_data = str(data)
        if len(log_data) > 500:
            log_data = log_data[:500] + "... [truncated]"

        logger.info(log_data)
        upload_id = data.get('id')
        if not upload_id:
            raise WhatsAppApiError('Upload session creation failed: missing session id', status_code=502)
        return upload_id
    except requests.exceptions.HTTPError as http_err:
        logger.error('Upload session HTTP error: %s - %s', http_err, response.text)
        raise WhatsAppApiError('Failed to create Meta upload session', status_code=response.status_code)
    except requests.exceptions.RequestException as req_err:
        logger.error('Upload session request error: %s', req_err)
        raise WhatsAppApiError('Failed to reach Meta upload session endpoint', status_code=502)


def _push_binary_to_graph_upload_session(waba_account, upload_id, raw_bytes):
    """
    Step 2 of Meta Resumable Upload API:
    POST /upload:<UPLOAD_SESSION_ID> with raw binary body.

    - Authorization: OAuth <token>   (NOT Bearer)
    - file_offset: 0                 (required header)
    - No Content-Type header (let requests/curl set it from binary body)
    - Body: raw bytes via --data-binary equivalent

    The upload_id must be used AS-IS: "upload:MTp..."
    Do NOT strip the "upload:" prefix.
    """
    # encoded_upload_id = quote(upload_id, safe=':')
    url = f"{get_base_url()}/{upload_id}"
    headers = {
        'Authorization': f'OAuth {waba_account.access_token}',
        'file_offset': '0',
    }

    try:
        logger.error(
            'Step 2 request: upload_id=%s encoded_upload_id=%s waba_id=%s raw_bytes=%s',
            upload_id,
            waba_account.waba_id,
            len(raw_bytes) if raw_bytes is not None else 0,
        )
        response = requests.post(url, headers=headers, data=raw_bytes, timeout=60)
        response.raise_for_status()
        data = response.json()
        header_handle = data.get('h')
        if not header_handle:
            logger.error('Binary upload response missing h: %s', data)
            raise WhatsAppApiError('Image binary upload failed: missing header handle in response', status_code=502)
        logger.error('Binary upload successful. header_handle prefix=%s length=%s', str(header_handle)[:30], len(str(header_handle)))
        return header_handle
    except requests.exceptions.HTTPError as http_err:
        logger.error('Binary upload HTTP error: %s - %s', http_err, response.text)
        raise WhatsAppApiError('Failed to upload image binary to Meta', status_code=response.status_code)
    except requests.exceptions.RequestException as req_err:
        logger.error('Binary upload request error: %s', req_err)
        raise WhatsAppApiError('Failed to reach Meta binary upload endpoint', status_code=502)


def _resolve_or_upload_header_handle(waba_account, payload, sample_image):
    """
    Full Meta Resumable Upload flow for IMAGE header templates:

    1. Check if payload already has a header_handle → skip upload entirely.
    2. Validate the uploaded image file (seek+tell for size, then seek back to 0).
    3. POST /{app-id}/uploads              → get upload_session_id
    4. Read raw bytes AFTER validation     → prevents empty read bug
    5. POST /{upload_session_id}           → push raw bytes, get 'h' handle
    6. Inject handle into component example block.
    """
    image_header_component = _extract_image_header_component(payload)
    if image_header_component is None:
        if sample_image:
            raise ValueError('sample_image can only be used when HEADER format is IMAGE')
        return None

    existing_header_handle = _get_existing_header_handle(image_header_component)
    if existing_header_handle and not sample_image:
        return existing_header_handle
    if existing_header_handle and sample_image:
        logger.info('Existing header_handle present, but sample_image provided; generating a fresh handle.')

    # _validate_sample_image does seek(0, SEEK_END) + seek(0) — stream is reset to 0 after
    filename, mime_type, file_size = _validate_sample_image(sample_image)

    try:
        # Read AFTER validation — stream is guaranteed at position 0 here
        raw_bytes = sample_image.read()
        if not raw_bytes:
            raise WhatsAppApiError('Image file is empty after reading', status_code=400)

        actual_file_size = len(raw_bytes)
        if actual_file_size != file_size:
            logger.warning(
                'Sample image size mismatch from stream metadata. using_actual_size=%s previous_size=%s filename=%s',
                actual_file_size,
                file_size,
                filename,
            )
            file_size = actual_file_size

        # Step 1: Create upload session → returns "upload:MTp..."
        upload_id = _create_graph_upload_session(
            waba_account,
            file_name=filename,
            file_length=file_size,
            file_type=mime_type,
        )
        logger.error('Upload session created: %s', upload_id)

        # Step 2: Push raw binary with OAuth + file_offset only (no explicit Content-Type)
        header_handle = _push_binary_to_graph_upload_session(
            waba_account,
            upload_id=upload_id,        # ← full "upload:MTp..." as-is
            raw_bytes=raw_bytes,
        )

        # Step 3: Inject into component example
        image_header_component['example'] = {'header_handle': [header_handle]}
        logger.error('Resolved header handle for template name=%s handle_prefix=%s', payload.get('name'), str(header_handle)[:30])
        return header_handle

    finally:
        try:
            sample_image.close()
        except Exception:
            pass

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
            elif header_type == "IMAGE":
                # Persist semantic type only; do not store Meta header_handle in DB.
                header_content = "IMAGE"
            else:
                header_content = header_type

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

        logger.error(
            'Meta error details: type=%s code=%s subcode=%s user_title=%s user_msg=%s fbtrace_id=%s',
            error_payload.get('type'),
            error_payload.get('code'),
            error_payload.get('error_subcode'),
            error_payload.get('error_user_title'),
            error_payload.get('error_user_msg'),
            error_payload.get('fbtrace_id'),
        )

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


# ───────────────────────────── ROUTES ─────────────────────────────


@templates_bp.route('', methods=['POST'])
@token_required
def create_template(decoded):
    try:
        waba_account = get_waba_account(decoded)
        payload, sample_image = _parse_template_creation_request()
        validate_template_payload(payload)

        logger.error('Create template request summary: %s', _payload_log_summary(payload))

        # Runs the full Meta Resumable Upload flow if IMAGE header is present,
        # and mutates payload's header component with the resolved header_handle.
        resolved_header_handle = _resolve_or_upload_header_handle(waba_account, payload, sample_image)
        if resolved_header_handle:
            logger.error(
                'Template create using header_handle prefix=%s length=%s',
                str(resolved_header_handle)[:30],
                len(str(resolved_header_handle)),
            )

        # Now submit the template to Meta — payload already has header_handle injected
        endpoint = f"{waba_account.waba_id}/message_templates"
        logger.error('Step 3 request: endpoint=%s summary=%s', endpoint, _payload_log_summary(payload))
        created = make_request_with_headers("POST", endpoint, waba_account, payload)
        logger.info(
            'Step 3 response: meta_template_id=%s status=%s category=%s',
            created.get('id'),
            created.get('status'),
            created.get('category'),
        )

        header_type, header_content, body_text, footer_text, buttons = extract_template_fields(payload)

        template = Template(
            waba_id=waba_account.waba_id,
            waba_account_id=waba_account.id,
            meta_template_id=created.get('id'),
            template_name=payload.get("name"),
            category=payload.get("category"),
            language=payload.get("language"),
            status=created.get("status", "PENDING"),
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
            "meta_template_id": template.meta_template_id,
            "name": template.template_name,
            "status": template.status,
        }), 201

    except ValueError as ve:
        logger.warning('Template validation error: %s', ve)
        return jsonify({'message': str(ve)}), 400
    except WhatsAppApiError as wae:
        logger.error('WhatsApp API error while creating template: status=%s message=%s', wae.status_code, wae.message)
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
    Returns templates stored locally in the Template table for this WABA account.
    Pending templates are refreshed from WhatsApp on every call.
    """
    try:
        waba_account = get_waba_account(decoded)
        templates = Template.query.filter_by(waba_account_id=waba_account.id).all()

        _refresh_pending_template_statuses(waba_account, templates)

        result = [
            {
                'id': t.id,
                'meta_template_id': t.meta_template_id,
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
