"""
Health check route for DreamPilot backend.
"""
from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
