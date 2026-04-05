"""
DreamPilot Backend - Main Application

A simple FastAPI backend with authentication.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
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


# Create FastAPI app (Swagger/OpenAPI enabled)
app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
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


@app.get("/swagger", include_in_schema=False)
async def swagger_redirect():
    """Redirect /swagger to FastAPI Swagger UI."""
    return RedirectResponse(url="/docs")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "DreamPilot API",
        "project": settings.PROJECT_NAME,
        "swagger": "/swagger",
        "docs": "/docs",
        "redoc": "/redoc"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
