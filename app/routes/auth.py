"""Authentication routes - login and registration."""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token
from app.models.user import User
from app.models import db
from app.utils.utils import success_response, error_response

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['POST'])
def register():
    """Register a new user.
    
    Expected JSON:
        {
            "username": "string",
            "email": "string",
            "password": "string"
        }
    
    Returns:
        JSON response with user data and token
    """
    data = request.get_json()
    # Check if user already exists
    if User.find_by_email(data['email']):
        return error_response('Email already registered', 409)
    
    if User.find_by_username(data['username']):
        return error_response('Username already taken', 409)
    
    # Create new user
    user = User(
        username=data['username'],
        email=data['email']
    )
    user.set_password(data['password'])
    
    try:
        db.session.add(user)
        db.session.commit()
        
        # Generate access token
        access_token = create_access_token(identity=str(user.id), additional_claims={'name': user.username, 'role': 'super-admin'})
        
        return success_response({
            'user': user.to_dict(),
            'access_token': access_token
        }, 'User registered successfully', 201)
    
    except Exception as e:
        print('e: ', e)
        db.session.rollback()
        return error_response('Registration failed', 500)


@auth_bp.route('/login', methods=['POST'])
def login():
    """Authenticate user and return token.
    
    Expected JSON:
        {
            "email": "string",
            "password": "string"
        }
    
    Returns:
        JSON response with user data and token
    """
    data = request.get_json()
    user = User.find_by_email(data['email'])
    
    if not user or not user.check_password(data['password']):
        return error_response('Invalid email or password', 401)
    
    # Generate access token
    access_token = create_access_token(identity=str(user.id), additional_claims={'name': user.username, 'role': 'super-admin'})
    
    return success_response({
        'user': user.to_dict(),
        'access_token': access_token
    }, 'Login successful')
