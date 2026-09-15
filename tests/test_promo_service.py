"""Promo service unit tests — validation matrix, percent math, redemption
idempotency, and Razorpay coupon caching. Pure-unit style (fake connection,
monkeypatched plan_cache / razorpay API) matching the plain pytest style of
tests/test_completion_service.py — no live DB or network."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import services.plan_cache as plan_cache
import database_adapter as database_adapter_module
import services.razorpay_service as razorpay_service
import services.promo_service as promo_service
from services.promo_service import (
    PromoValidationError,
    ensure_razorpay_coupon,
    mark_pending_redemption,
    mark_redeemed,
    normalize_code,
    validate_promo,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeConn:
    """Dispatches execute() by SQL shape and records mutations."""

    def __init__(self, *, promo=None, used=0, plan_price_cents=1900,
                 insert_conflict=False):
        self.promo = promo
        self.used = used
        self.plan_price_cents = plan_price_cents
        self.insert_conflict = insert_conflict
        self.statements = []
        self.redeemed_count = int(promo["redeemed_count"]) if promo else 0

    def execute(self, sql, params=None):
        self.statements.append(sql)
        cur = SimpleNamespace(fetchone=lambda: None)

        if "FROM promo_codes WHERE code" in sql:
            row = dict(self.promo) if self.promo else None
            row = dict(row) if row else None
            if row is not None:
                row["redeemed_count"] = self.redeemed_count
            cur.fetchone = (lambda r: (lambda: r))(row)
        elif "FROM promo_redemptions" in sql and "COUNT(*)" in sql:
            cur.fetchone = (lambda: {"n": self.used})
        elif "FROM billing_plans WHERE slug" in sql:
            cur.fetchone = (lambda: {
                "slug": params[0], "name": "Pro",
                "price_monthly_cents": self.plan_price_cents,
            })
        elif "INSERT INTO promo_redemptions" in sql:
            row = None if self.insert_conflict else {"id": 1}
            cur.fetchone = (lambda r: (lambda: r))(row)
        elif "UPDATE promo_redemptions" in sql:
            row = {"id": 1}
            cur.fetchone = (lambda r: (lambda: r))(row)
        elif "UPDATE promo_codes SET redeemed_count" in sql:
            self.redeemed_count += 1
            cur.fetchone = lambda: {"id": self.promo["id"]}
        return cur

    def commit(self):
        pass


def make_promo(**overrides):
    base = {
        "id": 7,
        "code": "SAVE20",
        "description": "20% off first payment",
        "discount_percent": 20.0,
        "max_redemptions": None,
        "per_user_limit": 1,
        "redeemed_count": 0,
        "active": True,
        "starts_at": None,
        "expires_at": None,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def fixed_inr_rate(monkeypatch):
    """Pin INR_PER_USD so INR math is deterministic (88, launch 25% off)."""
    monkeypatch.setattr(plan_cache, "get_billing_config",
                        lambda key, default=None: 88)


# ---------------------------------------------------------------------------
# normalize_code
# ---------------------------------------------------------------------------

def test_normalize_code_trims_and_uppercases():
    assert normalize_code("  save20 ") == "SAVE20"


# ---------------------------------------------------------------------------
# Validation matrix
# ---------------------------------------------------------------------------

def _validate(conn, code="SAVE20", user_id=1, plan="pro"):
    return validate_promo(conn, code, user_id, plan)


def test_validate_ok_percent_math_usd():
    result = _validate(FakeConn(promo=make_promo()))
    assert result["discount_percent"] == 20.0
    assert result["original_cents"] == 1900
    assert result["discounted_cents"] == 1520
    assert result["original_usd_display"] == "$19.00"
    assert result["discounted_usd_display"] == "$15.20"


def test_validate_inr_percent_off_real_plan_amount():
    """INR preview must equal what the Razorpay coupon charges: the percent
    applied to the real (launch-discounted, rounded) plan amount — NOT a
    re-conversion of the discounted USD (₹1,299 -20% = ₹1,039.20, not ₹999)."""
    result = _validate(FakeConn(promo=make_promo()))
    assert result["original_inr_paise"] == razorpay_service.usd_cents_to_inr_paise(1900)
    assert result["original_inr_paise"] == 129900          # ₹1,299
    assert result["discounted_inr_paise"] == 103920        # ₹1,039.20
    assert result["discounted_inr_display"] == "₹1,039"


def test_validate_pending_redemption_does_not_block_reuse():
    """An abandoned checkout ('pending' row) must not count as used — only
    redeemed redemptions consume the per-user limit."""
    class PendingOnlyConn(FakeConn):
        pass
    result = _validate(PendingOnlyConn(promo=make_promo()))
    assert result["discount_percent"] == 20.0


def test_validate_min_discount_floor():
    result = _validate(FakeConn(promo=make_promo(discount_percent=99)))
    assert result["discounted_cents"] == 50  # guarded from near-free


def test_validate_not_found():
    with pytest.raises(PromoValidationError) as e:
        _validate(FakeConn(promo=None))
    assert e.value.reason == "not_found"
    assert "Invalid promo code" in e.value.message


def test_validate_inactive():
    with pytest.raises(PromoValidationError) as e:
        _validate(FakeConn(promo=make_promo(active=False)))
    assert e.value.reason == "inactive"


def test_validate_not_yet_valid():
    future = datetime.utcnow() + timedelta(days=3)
    with pytest.raises(PromoValidationError) as e:
        _validate(FakeConn(promo=make_promo(starts_at=future)))
    assert e.value.reason == "not_yet_valid"


def test_validate_expired():
    past = datetime.utcnow() - timedelta(days=1)
    with pytest.raises(PromoValidationError) as e:
        _validate(FakeConn(promo=make_promo(expires_at=past)))
    assert e.value.reason == "expired"
    assert "expired" in e.value.message


def test_validate_fully_redeemed():
    with pytest.raises(PromoValidationError) as e:
        _validate(FakeConn(promo=make_promo(max_redemptions=10, redeemed_count=10)))
    assert e.value.reason == "fully_redeemed"


def test_validate_already_used():
    with pytest.raises(PromoValidationError) as e:
        _validate(FakeConn(promo=make_promo(), used=1))
    assert e.value.reason == "already_used"


def test_validate_free_plan_not_purchasable():
    with pytest.raises(PromoValidationError) as e:
        _validate(FakeConn(promo=make_promo(), plan_price_cents=0))
    assert e.value.reason == "plan_not_purchasable"


# ---------------------------------------------------------------------------
# Redemption lifecycle (idempotency)
# ---------------------------------------------------------------------------

def test_mark_pending_inserts_once():
    conn = FakeConn(promo=make_promo())
    assert mark_pending_redemption(conn, 7, 1, "razorpay", "sub_1") is True
    conflict = FakeConn(promo=make_promo(), insert_conflict=True)
    assert mark_pending_redemption(conflict, 7, 1, "razorpay", "sub_1") is False


def test_mark_redeemed_bumps_count_once():
    conn = FakeConn(promo=make_promo())
    assert mark_redeemed(conn, 7, 1, "sub_1") is True
    assert conn.redeemed_count == 1
    # Second call (webhook after verify) is a no-op.
    empty = FakeConn(promo=make_promo())
    empty.fetchone_returns = None
    # simulate already-redeemed: UPDATE matches no rows
    class OnceConn(FakeConn):
        def execute(self, sql, params=None):
            cur = super().execute(sql, params)
            if "UPDATE promo_redemptions" in sql:
                cur.fetchone = lambda: None
            return cur
    assert mark_redeemed(OnceConn(promo=make_promo()), 7, 1, "sub_1") is False


# ---------------------------------------------------------------------------
# Razorpay coupon mirroring + caching
# ---------------------------------------------------------------------------

def test_ensure_razorpay_coupon_creates_once_and_caches(monkeypatch):
    calls = []

    def fake_api(method, path, *, json_body=None, params=None):
        calls.append((method, path, json_body))
        assert path == "/coupons"
        assert json_body["discount_type"] == "percent"
        assert json_body["percent"] == 20.0
        assert json_body["duration_type"] == "months"
        assert json_body["duration"] == 1
        return {"id": "coupon_ABC123"}

    monkeypatch.setattr(razorpay_service, "_api", fake_api)

    # Map starts empty; DB save goes to a fake conn.
    monkeypatch.setattr(plan_cache, "get_billing_config",
                        lambda key, default=None: {} if key == promo_service.PROMO_COUPON_MAP_KEY else 88)
    saved = {}

    class MapSaveConn:
        def execute(self, sql, params=None):
            if "billing_config" in sql:
                saved["value"] = params[1]
            return SimpleNamespace(fetchone=lambda: None)

        def commit(self):
            pass

    monkeypatch.setattr(database_adapter_module, "get_db",
                        lambda: MapSaveConn())

    promo = make_promo()
    assert ensure_razorpay_coupon(promo) == "coupon_ABC123"
    assert len(calls) == 1

    # Cached map now returns the id — no second API call.
    monkeypatch.setattr(plan_cache, "get_billing_config",
                        lambda key, default=None: {"SAVE20": "coupon_ABC123"}
                        if key == promo_service.PROMO_COUPON_MAP_KEY else 88)
    assert ensure_razorpay_coupon(promo) == "coupon_ABC123"
    assert len(calls) == 1


def test_ensure_razorpay_coupon_unlimited_uses_cap(monkeypatch):
    body = {}

    def fake_api(method, path, *, json_body=None, params=None):
        body.update(json_body)
        return {"id": "coupon_X"}

    monkeypatch.setattr(razorpay_service, "_api", fake_api)
    monkeypatch.setattr(plan_cache, "get_billing_config", lambda key, default=None: {})
    monkeypatch.setattr(database_adapter_module, "get_db",
                        lambda: SimpleNamespace(
                            execute=lambda *a, **k: SimpleNamespace(fetchone=lambda: None),
                            commit=lambda: None))
    ensure_razorpay_coupon(make_promo(max_redemptions=None))
    assert body["max_count"] == 1000
    ensure_razorpay_coupon(make_promo(max_redemptions=5, redeemed_count=2))
    assert body["max_count"] == 3
