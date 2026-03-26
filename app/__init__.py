"""Application factory for Flask application."""
import os
import logging
from flask import Flask, request
from flask_cors import CORS
from celery import Celery
from app.config import config_by_name
from app.database import init_db
from app.logging_config import setup_flask_logging, setup_celery_logging


# Module-level celery instance
celery = Celery(__name__, broker='redis://localhost:6379/1')


celery.conf.update(
    broker_url='redis://localhost:6379/1',
    result_backend='redis://localhost:6379/1',
    include=['app.tasks.whatsapp_tasks'],
    task_default_queue='whatsapp',
    worker_pool='threads',
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

setup_celery_logging()

_worker_app = None


def _get_worker_app():
    """Lazily create Flask app used by Celery worker tasks."""
    global _worker_app
    if _worker_app is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
        _worker_app = create_app(config_name)
    return _worker_app


class ContextTask(celery.Task):
    """Celery task that runs with Flask app context."""
    def __call__(self, *args, **kwargs):
        app = _get_worker_app()
        with app.app_context():
            return self.run(*args, **kwargs)


celery.Task = ContextTask

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
    setup_flask_logging(app)
    app.config.from_object(config_by_name[config_name])

    logging.getLogger(__name__).setLevel(logging.INFO)
    
    # Suppress verbose logging from SQLAlchemy and other libraries
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
    # logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    # Initialize database, migrations, and JWT
    init_db(app)
    
    # Enable CORS globally and ensure preflight requests are handled.
    raw_origins = app.config.get('ALLOWED_ORIGINS', ['http://localhost:5173'])
    if isinstance(raw_origins, str):
        raw_origins = raw_origins.split(',')
    allowed_origins = [origin.strip() for origin in raw_origins if origin and origin.strip()]
    allow_any_origin = '*' in allowed_origins

    # Build CORS config with proper credentials handling
    cors_origins = '*' if allow_any_origin else allowed_origins
    
    # If using wildcard, don't require credentials; if using specific origins, allow them
    cors_config = {
        r"/*": {
            'origins': cors_origins,
            'methods': ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
            'allow_headers': ['Authorization', 'Content-Type', 'Accept'],
            'expose_headers': ['Content-Type', 'Content-Length'],
            'max_age': 86400,
            'supports_credentials': True if not allow_any_origin else False,
        }
    }

    CORS(app, resources=cors_config)
    
    # Register blueprints with URL prefixes
    from app.routes.auth import auth_bp
    from app.routes.users import users_bp
    from app.routes.embedded_signup import meta_bp
    from app.routes.webhook import webhook_bp
    from app.routes.templates import templates_bp
    from app.routes.chat import chat_bp
    from app.routes.dashboard import dashboard_bp
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(users_bp)
    app.register_blueprint(meta_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(templates_bp, url_prefix='/templates')
    app.register_blueprint(chat_bp)
    app.register_blueprint(dashboard_bp)
    
    @app.after_request
    def log_request(response):
        logging.getLogger(__name__).info(
            '%s %s %s', request.method, request.path, response.status_code
        )
        return response
    
    return app
