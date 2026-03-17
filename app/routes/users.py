"""User CRUD operations routes."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.user import User
from app.models.whatsapp import WabaAccount
from app.models import db
from app.utils.utils import success_response, error_response

users_bp = Blueprint('users', __name__)


@users_bp.route('/', methods=['GET'])
@jwt_required()
def get_users():
    """Get all users (paginated).
    
    Query Parameters:
        page: Page number (default: 1)
        per_page: Items per page (default: 10)
    
    Returns:
        JSON response with list of users
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    pagination = User.query.paginate(page=page, per_page=per_page, error_out=False)
    
    users = [user.to_dict() for user in pagination.items]
    
    return success_response({
        'users': users,
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages
    })


@users_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get currently authenticated user.
    
    Returns:
        JSON response with current user data
    """
    current_user_id = get_jwt_identity()
    user = User.find_by_id(current_user_id)
    
    if not user:
        return error_response('User not found', 404)
    
    return success_response({'user': user.to_dict()})


@users_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """Get currently authenticated user's profile.
    
    Returns:
        JSON response with user profile data
    """
    current_user_id = get_jwt_identity()
    user = User.find_by_id(current_user_id)
    
    if not user:
        return error_response('User not found', 404)

    user_data = user.to_dict()
    has_whatsapp_account = WabaAccount.query.filter_by(user_id=current_user_id).first() is not None

    if has_whatsapp_account:
        user_data['whatsapp_status'] = 'connected'

    return success_response({'user': user_data})


@users_bp.route('/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    """Update currently authenticated user's profile.
    
    Expected JSON:
        {
            "username": "string" (optional, user's display name),
            "phone_number": "string" (optional)
        }
    
    Note: Email cannot be changed after account creation.
    
    Returns:
        JSON response with updated user profile
    """
    data = request.get_json()
    current_user_id = get_jwt_identity()
    
    user = User.find_by_id(current_user_id)
    
    if not user:
        return error_response('User not found', 404)
    
    # Allow username (name) updates
    if 'username' in data:
        user.username = data['username']
    
    # Allow phone_number updates
    if 'phone_number' in data:
        user.phone_number = data['phone_number']
    
    # Reject any attempt to change email
    if 'email' in data:
        return error_response('Email cannot be changed', 400)
    
    try:
        db.session.commit()
        return success_response({'user': user.to_dict()}, 'User updated successfully')
    except Exception as e:
        db.session.rollback()
        return error_response('Update failed', 500)


@users_bp.route('/change-password', methods=['PUT'])
@jwt_required()
def change_password():
    """Change the authenticated user's password.

    Expected JSON:
        {
            "oldPassword": "string",
            "newPassword": "string"
        }
    """
    data = request.get_json() or {}
    old_password = data.get('oldPassword')
    new_password = data.get('newPassword')

    if not old_password or not new_password:
        return error_response('oldPassword and newPassword are required', 400)

    current_user_id = get_jwt_identity()
    user = User.find_by_id(current_user_id)

    if not user:
        return error_response('User not found', 404)

    if not user.check_password(old_password):
        return error_response('Current password is incorrect', 401)

    if old_password == new_password:
        return error_response('New password must be different from current password', 400)

    try:
        user.set_password(new_password)
        db.session.commit()
        return success_response({}, 'Password updated successfully', 200)
    except Exception:
        db.session.rollback()
        return error_response('Failed to update password', 500)


@users_bp.route('/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user(user_id):
    """Get a specific user by ID.
    
    Args:
        user_id: User ID
    
    Returns:
        JSON response with user data
    """
    user = User.find_by_id(user_id)
    
    if not user:
        return error_response('User not found', 404)
    
    return success_response({'user': user.to_dict()})


@users_bp.route('/<int:user_id>', methods=['PUT'])
@jwt_required()
def update_user(user_id):
    """Update user name and phone number.
    
    Args:
        user_id: User ID to update
    
    Expected JSON:
        {
            "username": "string" (optional, user's display name),
            "phone_number": "string" (optional)
        }
    
    Note: Email cannot be changed after account creation.
    
    Returns:
        JSON response with updated user data
    """
    data = request.get_json()
    current_user_id = get_jwt_identity()
    
    # Only allow users to update their own profile
    if current_user_id != user_id:
        return error_response('Unauthorized', 403)
    
    user = User.find_by_id(user_id)
    
    if not user:
        return error_response('User not found', 404)
    
    # Allow username (name) updates
    if 'username' in data:
        user.username = data['username']
    
    # Allow phone_number updates
    if 'phone_number' in data:
        user.phone_number = data['phone_number']
    
    # Reject any attempt to change email
    if 'email' in data:
        return error_response('Email cannot be changed', 400)
    
    try:
        db.session.commit()
        return success_response({'user': user.to_dict()}, 'User updated successfully')
    except Exception as e:
        db.session.rollback()
        return error_response('Update failed', 500)


@users_bp.route('/<int:user_id>', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    """Delete a user.
    
    Args:
        user_id: User ID to delete
    
    Returns:
        JSON response confirming deletion
    """
    current_user_id = get_jwt_identity()
    
    # Only allow users to delete their own account
    if current_user_id != user_id:
        return error_response('Unauthorized', 403)
    
    user = User.find_by_id(user_id)
    
    if not user:
        return error_response('User not found', 404)
    
    try:
        db.session.commit()
        return success_response({'user': user.to_dict()}, 'Profile updated successfully')
    except Exception as e:
        db.session.rollback()
        return error_response('Update failed', 500)
