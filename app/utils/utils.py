"""Utility functions and helpers."""
from functools import wraps
from flask import jsonify, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity


def jwt_required_custom(f):
    """Custom JWT required decorator with error handling.
    
    Returns:
        Decorator function
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            verify_jwt_in_request()
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'error': 'Invalid or expired token'}), 401
    return decorated_function


def success_response(data, message='Success', status_code=200):
    """Create a standardized success response.
    
    Args:
        data: Response data
        message: Success message
        status_code: HTTP status code
    
    Returns:
        JSON response tuple
    """
    return jsonify({
        'success': True,
        'message': message,
        'data': data
    }), status_code


def error_response(message, status_code=400):
    """Create a standardized error response.
    
    Args:
        message: Error message
        status_code: HTTP status code
    
    Returns:
        JSON response tuple
    """
    return jsonify({
        'success': False,
        'error': message
    }), status_code
