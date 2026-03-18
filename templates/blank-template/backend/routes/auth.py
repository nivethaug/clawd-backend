"""
Authentication routes for DreamPilot backend.
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from core.database import get_db
from services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["Auth"])


# Request/Response models
class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str


class TokenResponse(BaseModel):
    token: str


class MessageResponse(BaseModel):
    message: str


@router.post("/register", response_model=MessageResponse)
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user."""
    user = AuthService.register(db, request.email, request.password)
    
    if not user:
        raise HTTPException(status_code=400, detail="Email already exists")
    
    return {"message": "User created"}


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Login and get token."""
    token = AuthService.login(db, request.email, request.password)
    
    if not token:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    return {"token": token}


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Get current user from token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    token = parts[1]
    user = AuthService.get_user_by_token(db, token)
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return {"id": user.id, "email": user.email}
