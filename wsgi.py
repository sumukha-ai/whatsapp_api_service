"""WSGI entry point for production deployment."""
import os
from app import create_app

# Get environment from environment variable or default to development
config_name = os.environ.get('FLASK_ENV', 'development')

# Create application instance
app = create_app(config_name)

if __name__ == '__main__':
    app.run()
