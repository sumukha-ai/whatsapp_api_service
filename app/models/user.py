"""User model for authentication and user management."""
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import db


class User(db.Model):
    """User model representing application users.
    
    Attributes:
        id: Primary key
        username: User's display name
        email: Unique email address
        phone_number: User's phone number
        password_hash: Hashed password
        created_at: Account creation timestamp
        updated_at: Last update timestamp
    """
    
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone_number = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        """String representation of User."""
        return f'<User {self.username}>'
    
    def set_password(self, password):
        """Hash and set user password.
        
        Args:
            password: Plain text password
        """
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password against stored hash.
        
        Args:
            password: Plain text password to verify
        
        Returns:
            bool: True if password matches, False otherwise
        """
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        """Convert user object to dictionary.
        
        Returns:
            dict: User data without sensitive information
        """
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'phone_number': self.phone_number,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    @classmethod
    def find_by_email(cls, email):
        """Find user by email address.
        
        Args:
            email: Email address to search for
        
        Returns:
            User instance or None
        """
        return cls.query.filter_by(email=email).first()
    
    @classmethod
    def find_by_username(cls, username):
        """Find user by username.
        
        Args:
            username: Username to search for
        
        Returns:
            User instance or None
        """
        return cls.query.filter_by(username=username).first()
    
    @classmethod
    def find_by_id(cls, user_id):
        """Find user by ID.
        
        Args:
            user_id: User ID to search for
        
        Returns:
            User instance or None
        """
        return cls.query.get(int(user_id))
