"""
Authentication service for DreamPilot backend.
"""
import bcrypt
from sqlalchemy.orm import Session
from ..models.user import User


class AuthService:
    """Simple authentication service."""
    
    # In-memory token store (simple-token -> user_id)
    TOKENS: dict = {}
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash password using bcrypt."""
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify password against hash."""
        return bcrypt.checkpw(
            password.encode('utf-8'),
            password_hash.encode('utf-8')
        )
    
    @classmethod
    def create_user(cls, db: Session, email: str, password: str) -> User:
        """Create a new user."""
        password_hash = cls.hash_password(password)
        user = User(email=email, password_hash=password_hash)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    
    @classmethod
    def get_user_by_email(cls, db: Session, email: str) -> User | None:
        """Get user by email."""
        return db.query(User).filter(User.email == email).first()
    
    @classmethod
    def get_user_by_id(cls, db: Session, user_id: int) -> User | None:
        """Get user by ID."""
        return db.query(User).filter(User.id == user_id).first()
    
    @classmethod
    def login(cls, db: Session, email: str, password: str) -> str | None:
        """Login user and return token."""
        user = cls.get_user_by_email(db, email)
        if not user:
            return None
        
        if not cls.verify_password(password, user.password_hash):
            return None
        
        # Generate simple token
        token = f"token-{user.id}-{user.email.split('@')[0]}"
        cls.TOKENS[token] = user.id
        return token
    
    @classmethod
    def get_user_by_token(cls, db: Session, token: str) -> User | None:
        """Get user by token."""
        user_id = cls.TOKENS.get(token)
        if not user_id:
            return None
        return cls.get_user_by_id(db, user_id)
    
    @classmethod
    def register(cls, db: Session, email: str, password: str) -> User | None:
        """Register a new user."""
        # Check if user exists
        existing = cls.get_user_by_email(db, email)
        if existing:
            return None
        
        # Create user
        return cls.create_user(db, email, password)
    
    @classmethod
    def ensure_default_user(cls, db: Session) -> User:
        """Ensure default test user exists."""
        default_email = "test@dreampilot.com"
        default_password = "123456"
        
        user = cls.get_user_by_email(db, default_email)
        if not user:
            user = cls.create_user(db, default_email, default_password)
            print(f"✓ Default user created: {default_email}")
        else:
            print(f"✓ Default user exists: {default_email}")
        
        return user
