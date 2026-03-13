"""Database initialization and management."""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager

# Initialize database, migration, and JWT managers
db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()


def init_db(app):
    """Initialize database with Flask app.
    
    Args:
        app: Flask application instance
    """
    # Initialize all extensions with Flask app
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    
    with app.app_context():
        # Import all models here to register them with SQLAlchemy
        # This ensures they're registered with the metadata before migrations run
        from app.models.user import User  # noqa: F401
        from app.models.whatsapp import (  # noqa: F401
            Contact,
            Conversation,
            Group,
            GroupContact,
            Message,
            Template,
            WabaAccount,
            WebhookLog,
        )
        
        # Create tables if using SQLite or for development without migrations
        # In production with migrations, this step is handled by 'flask db upgrade'
        # db.create_all()
        
        return db
