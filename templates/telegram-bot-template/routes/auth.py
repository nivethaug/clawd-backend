"""
Authentication routes for Telegram bot backend.
Telegram users are authenticated via their Telegram ID.
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from pydantic import BaseModel

from core.database import get_db
from models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

# Security
security = HTTPBearer()

# JWT Config (should be in .env in production)
SECRET_KEY = "your-secret-key-change-in-production"  # TODO: Move to .env
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24


# Pydantic models
class Token(BaseModel):
    access_token: str
    token_type: str


class UserInfo(BaseModel):
    id: int
    email: Optional[str]
    telegram_user_id: Optional[int]
    
    class Config:
        from_attributes = True


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current user from JWT token."""
    # Database not configured
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured - authentication unavailable"
        )
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        telegram_user_id: str = payload.get("sub")
        if telegram_user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.telegram_user_id == int(telegram_user_id)).first()
    if user is None:
        raise credentials_exception
    return user


@router.post("/telegram", response_model=Token)
async def telegram_login(telegram_user_id: int, db: Session = Depends(get_db)):
    """Login via Telegram user ID."""
    # Database not configured
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured - login unavailable"
        )
    
    user = db.query(User).filter(User.telegram_user_id == telegram_user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram user not found"
        )
    
    # Create access token
    access_token = create_access_token(data={"sub": str(user.telegram_user_id)})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserInfo)
async def get_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information."""
    return current_user
