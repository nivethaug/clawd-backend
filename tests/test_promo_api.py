"""Promo router API tests — /validate happy path + failure reasons, admin
auth enforcement, and create-code validation. Uses a bare FastAPI app with
the promo router; auth + DB are monkeypatched (no live app.py import, no
network, no database)."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import api.promo_router as promo_router
from api.promo_router import CreatePromoRequest, router

from tests.test_promo_service import FakeConn, make_promo  # fakes reuse


@pytest.fixture()
def client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr(promo_router, "_get_user_id", lambda auth=None: 1)
    # Admin routes must not import the real app (which touches the DB).
    monkeypatch.setattr(promo_router, "_require_admin", lambda user_id: None)
    return TestClient(app)


def _set_db(monkeypatch, conn):
    class _Ctx:
        def __enter__(self):
            return conn

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(promo_router, "get_db", lambda: _Ctx())


# ---------------------------------------------------------------------------
# /validate
# ---------------------------------------------------------------------------

def test_validate_ok(client, monkeypatch):
    _set_db(monkeypatch, FakeConn(promo=make_promo()))
    resp = client.post("/validate", json={"code": "save20", "plan_slug": "pro"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["code"] == "SAVE20"
    assert data["discount_percent"] == 20.0
    assert data["discounted_usd_display"] == "$15.20"
    assert data["discounted_inr_display"] == "₹1,039"


def test_validate_invalid_code_422(client, monkeypatch):
    _set_db(monkeypatch, FakeConn(promo=None))
    resp = client.post("/validate", json={"code": "NOPE", "plan_slug": "pro"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["reason"] == "not_found"
    assert "Invalid promo code" in detail["message"]


def test_validate_expired_422(client, monkeypatch):
    from datetime import datetime, timedelta
    past = datetime.utcnow() - timedelta(days=2)
    _set_db(monkeypatch, FakeConn(promo=make_promo(expires_at=past)))
    resp = client.post("/validate", json={"code": "SAVE20", "plan_slug": "pro"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["reason"] == "expired"


def test_validate_already_used_422(client, monkeypatch):
    _set_db(monkeypatch, FakeConn(promo=make_promo(), used=1))
    resp = client.post("/validate", json={"code": "SAVE20", "plan_slug": "pro"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["reason"] == "already_used"


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

def test_admin_requires_admin_role(client, monkeypatch):
    def deny(user_id):
        raise HTTPException(status_code=403, detail="Admin access required")

    monkeypatch.setattr(promo_router, "_require_admin", deny)
    resp = client.get("/admin/codes")
    assert resp.status_code == 403


def test_create_promo_code_validation():
    with pytest.raises(ValueError):
        CreatePromoRequest(code="AB", discount_percent=20)  # too short
    with pytest.raises(ValueError):
        CreatePromoRequest(code="BAD CODE!", discount_percent=20)  # bad chars
    with pytest.raises(ValueError):
        CreatePromoRequest(code="SAVE20", discount_percent=0)  # out of range
    with pytest.raises(ValueError):
        CreatePromoRequest(code="SAVE20", discount_percent=101)
    with pytest.raises(ValueError):
        CreatePromoRequest(code="SAVE20", discount_percent=20, max_redemptions=0)
    ok = CreatePromoRequest(code=" save20 ", discount_percent=20, max_redemptions=None)
    assert ok.code == "SAVE20"


def test_create_promo_code_duplicate_409(client, monkeypatch):
    class DupConn(FakeConn):
        def execute(self, sql, params=None):
            if "SELECT id FROM promo_codes WHERE code" in sql:
                return type("C", (), {"fetchone": lambda s: {"id": 1}})()
            return super().execute(sql, params)

    _set_db(monkeypatch, DupConn(promo=make_promo()))
    resp = client.post("/admin/codes",
                       json={"code": "SAVE20", "discount_percent": 20})
    assert resp.status_code == 409


def test_patch_promo_not_found(client, monkeypatch):
    class MissingConn(FakeConn):
        def execute(self, sql, params=None):
            cur = super().execute(sql, params)
            if "UPDATE promo_codes SET active" in sql:
                cur.fetchone = lambda: None
            return cur

    _set_db(monkeypatch, MissingConn(promo=make_promo()))
    resp = client.patch("/admin/codes/999", json={"active": False})
    assert resp.status_code == 404
