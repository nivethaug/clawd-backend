"""
Initialize DreamPilot backend.
Run this to set up the database and default user.
"""
from core.database import init_db, SessionLocal
from services.auth_service import AuthService


def main():
    """Initialize backend."""
    print("🚀 Initializing DreamPilot Backend...")
    
    # Create tables
    print("📋 Creating database tables...")
    init_db()
    print("✓ Tables created")
    
    # Ensure default user
    print("👤 Ensuring default user...")
    db = SessionLocal()
    try:
        AuthService.ensure_default_user(db)
    finally:
        db.close()
    
    print("✅ Backend initialized successfully!")
    print("")
    print("Default credentials:")
    print("  Email: test@dreampilot.com")
    print("  Password: 123456")


if __name__ == "__main__":
    main()
