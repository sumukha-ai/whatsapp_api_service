"""Configuration settings for different environments."""
import os
from datetime import timedelta
from dotenv import load_dotenv
from pathlib import Path


# Load environment variables from .env file
load_dotenv(dotenv_path=Path('.') / '.env')


class Config:
    """Base configuration."""
    # Secret keys
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production')
    
    # JWT Configuration
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    
    # SQLAlchemy Configuration
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    
    # CORS Configuration
    ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '*').split(',')

    # Backend URL used to build public callback/webhook URLs.
    BACKEND_URL = os.environ.get('BACKEND_URL', 'http://127.0.0.1:5000')

    # Meta/WhatsApp Embedded Signup configuration.
    META_CLIENT_ID = os.environ.get('CLIENT_ID')
    META_CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
    META_GRANT_TYPE = os.environ.get('GRANT_TYPE', 'authorization_code')
    WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.environ.get('WHATSAPP_WEBHOOK_VERIFY_TOKEN', 'thisIsASuperSecretToken')
    WHATSAPP_REGISTRATION_PIN = os.environ.get('WHATSAPP_REGISTRATION_PIN', '654321')
    
class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/interview_web_app_dev'
    )


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'TEST_DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/interview_web_app_test'
    )


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("DATABASE_URL environment variable is required in production")


config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig
}
