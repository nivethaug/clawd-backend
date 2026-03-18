"""
DreamPilot Backend - Main Application

A simple FastAPI backend with authentication.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from core.config import settings
from core.database import init_db, SessionLocal
from services.auth_service import AuthService
from routes.health import router as health_router
from routes.auth import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - initialize on startup."""
    # Create database tables
    print("🔧 Initializing database...")
    init_db()
    print("✓ Database tables created")
    
    # Ensure default user exists
    print("🔧 Ensuring default user...")
    db = SessionLocal()
    try:
        AuthService.ensure_default_user(db)
    finally:
        db.close()
    
    print(f"🚀 {settings.PROJECT_NAME} is ready!")
    yield


# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(auth_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "DreamPilot API",
        "project": settings.PROJECT_NAME,
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
