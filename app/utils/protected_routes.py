from functools import wraps

import jwt
from flask import request, jsonify, current_app


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        # Check if the JWT is passed in the Authorization header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(" ")[1]

        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        try:
            # Decode the token using the secret key and algorithm
            secret_key = current_app.config.get('JWT_SECRET_KEY')
            if not secret_key:
                return jsonify({'message': 'Server JWT configuration is missing'}), 500

            decoded_payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token has expired!'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Invalid token!'}), 401

        # Pass the decoded payload to the actual endpoint
        return f(decoded_payload, *args, **kwargs)

    return decorated
