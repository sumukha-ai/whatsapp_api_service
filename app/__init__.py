"""Application factory for Flask application."""
import logging
from flask import Flask
from flask_cors import CORS
from app.config import config_by_name
from app.database import init_db


def create_app(config_name='development'):
    """Create and configure the Flask application.
    
    Uses the application factory pattern with lazy initialization of database,
    migrations, and JWT authentication.
    
    Args:
        config_name: Configuration environment (development, testing, production)
    
    Returns:
        Flask application instance with all extensions initialized
    """
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])
    
    # Suppress verbose logging from SQLAlchemy and other libraries
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
    # logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    # Initialize database, migrations, and JWT
    init_db(app)
    
    # Enable CORS with allowed origins from config
    allowed_origins = app.config.get('ALLOWED_ORIGINS', ['http://localhost:5173'])
    CORS(app, origins=allowed_origins, supports_credentials=True)
    
    # Register blueprints with URL prefixes
    from app.routes.auth import auth_bp
    from app.routes.users import users_bp
    from app.routes.embedded_signup import meta_bp
    from app.routes.webhook import webhook_bp
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(users_bp)
    app.register_blueprint(meta_bp)
    app.register_blueprint(webhook_bp)
    
    return app
