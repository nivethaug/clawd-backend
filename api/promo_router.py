#!/usr/bin/env python3
"""
Promo API Router — validation + admin management for percent-off promo codes
(subscription plans, first charge only, USD + INR).

Prefix: /api/billing/promo  (mounted in app.py next to billing_router)
Auth: Bearer token. Admin routes additionally require the admin role.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator

from database_postgres import get_db

logger = logging.getLogger("api.promo")

router = APIRouter()


def _get_user_id(authorization: Optional[str] = None) -> int:
    from app import get_user_id_from_token
    return get_user_id_from_token(authorization)


def _require_admin(user_id: int):
    from app import require_admin
    require_admin(user_id)


# ============================================================================
# Pydantic Models
# ============================================================================

class ValidatePromoRequest(BaseModel):
    code: str
    plan_slug: str


class CreatePromoRequest(BaseModel):
    code: str
    discount_percent: float
    description: Optional[str] = None
    max_redemptions: Optional[int] = None
    per_user_limit: int = 1
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    @field_validator("code")
    @classmethod
    def _code_shape(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not (3 <= len(v) <= 40) or not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Code must be 3-40 letters/digits (dashes/underscores allowed).")
        return v

    @field_validator("discount_percent")
    @classmethod
    def _percent_range(cls, v: float) -> float:
        if not (0 < v <= 100):
            raise ValueError("Discount percent must be between 0 and 100.")
        return v

    @field_validator("max_redemptions")
    @classmethod
    def _max_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("Max redemptions must be at least 1.")
        return v

    @field_validator("per_user_limit")
    @classmethod
    def _per_user_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Per-user limit must be at least 1.")
        return v


class UpdatePromoRequest(BaseModel):
    active: Optional[bool] = None


# ============================================================================
# Validation (authenticated, pre-payment)
# ============================================================================

@router.post("/validate")
async def validate_promo_code(request: ValidatePromoRequest, authorization: Optional[str] = Header(None)):
    """Validate a promo code against a plan and return the discounted
    first-charge preview prices. 422 with a clear message on failure."""
    user_id = _get_user_id(authorization)
    from services.promo_service import PromoValidationError, validate_promo

    with get_db() as conn:
        try:
            result = validate_promo(conn, request.code, user_id, request.plan_slug)
        except PromoValidationError as e:
            raise HTTPException(status_code=422, detail={"reason": e.reason, "message": e.message})

    promo = result["promo"]
    return {
        "valid": True,
        "code": promo["code"],
        "description": promo.get("description"),
        "discount_percent": result["discount_percent"],
        "original_usd_display": result["original_usd_display"],
        "discounted_usd_display": result["discounted_usd_display"],
        "original_inr_display": result["original_inr_display"],
        "discounted_inr_display": result["discounted_inr_display"],
    }


# ============================================================================
# Admin management
# ============================================================================

def _promo_row_to_dict(row) -> dict:
    d = dict(row) if not isinstance(row, dict) else row
    for key in ("starts_at", "expires_at", "created_at"):
        if isinstance(d.get(key), datetime):
            d[key] = d[key].isoformat()
    return d


@router.get("/admin/codes")
async def list_promo_codes(authorization: Optional[str] = Header(None)):
    user_id = _get_user_id(authorization)
    _require_admin(user_id)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM promo_codes ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    return {"codes": [_promo_row_to_dict(r) for r in rows]}


@router.post("/admin/codes")
async def create_promo_code(request: CreatePromoRequest, authorization: Optional[str] = Header(None)):
    user_id = _get_user_id(authorization)
    _require_admin(user_id)
    from services.promo_service import normalize_code

    code = normalize_code(request.code)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM promo_codes WHERE code = %s", (code,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail={"message": "A promo code with this name already exists."})
        cur = conn.execute(
            """INSERT INTO promo_codes
                 (code, description, discount_percent, max_redemptions,
                  per_user_limit, active, starts_at, expires_at)
               VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s)
               RETURNING *""",
            (
                code,
                request.description,
                request.discount_percent,
                request.max_redemptions,
                request.per_user_limit,
                request.starts_at,
                request.expires_at,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    return {"code": _promo_row_to_dict(row)}


@router.patch("/admin/codes/{promo_id}")
async def update_promo_code(promo_id: int, request: UpdatePromoRequest,
                            authorization: Optional[str] = Header(None)):
    user_id = _get_user_id(authorization)
    _require_admin(user_id)
    if request.active is None:
        raise HTTPException(status_code=400, detail={"message": "Nothing to update."})
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE promo_codes SET active = %s WHERE id = %s RETURNING *",
            (request.active, promo_id),
        )
        row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail={"message": "Promo code not found."})
    return {"code": _promo_row_to_dict(row)}
