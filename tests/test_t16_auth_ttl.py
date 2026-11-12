"""T16: auth token TTL + cache freshness."""

import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

app = audit_conftest.app_module


def _auth(header):
    return app.get_user_id_from_token(header)


def test_t16_expired_token_401(monkeypatch):
    from audit_conftest import make_fake_db
    # DB returns nothing (token too old → filtered by the TTL clause)
    monkeypatch.setattr(app, "get_db", make_fake_db([]))
    monkeypatch.delenv("AUTH_TOKEN_TTL_DAYS", raising=False)
    app.AUTH_TOKENS.pop("oldtok", None)
    app._AUTH_TOKEN_CACHED_AT.pop("oldtok", None)
    with pytest.raises(HTTPException) as ei:
        _auth("Bearer oldtok")
    assert ei.value.status_code == 401


def test_t16_valid_token_cached_with_stamp(monkeypatch):
    from audit_conftest import make_fake_db, FakeRow
    db = make_fake_db([("SELECT user_id FROM auth_tokens", [FakeRow(user_id=7)])])
    monkeypatch.setattr(app, "get_db", db)
    app.AUTH_TOKENS.pop("freshtok", None)
    uid = _auth("Bearer freshtok")
    assert uid == 7
    assert app.AUTH_TOKENS.get("freshtok") == 7
    assert "freshtok" in app._AUTH_TOKEN_CACHED_AT


def test_t16_stale_cache_requeries_db(monkeypatch):
    from audit_conftest import make_fake_db, FakeRow
    # seed a STALE cache entry
    app.AUTH_TOKENS["staletok"] = 9
    app._AUTH_TOKEN_CACHED_AT["staletok"] = 0.0  # ancient
    db = make_fake_db([("SELECT user_id FROM auth_tokens", [FakeRow(user_id=9)])])
    monkeypatch.setattr(app, "get_db", db)
    uid = _auth("Bearer staletok")
    assert uid == 9
    # re-stamped
    assert app._AUTH_TOKEN_CACHED_AT["staletok"] > 0
    # ...and when the DB no longer knows the token, the stale entry 401s
    monkeypatch.setattr(app, "get_db", make_fake_db([]))
    app._AUTH_TOKEN_CACHED_AT["staletok"] = 0.0
    with pytest.raises(HTTPException):
        _auth("Bearer staletok")


def test_t16_synthetic_proxy_tokens_bypass_db(monkeypatch):
    from audit_conftest import make_fake_db
    app.AUTH_TOKENS["proxy-42"] = 42
    monkeypatch.setattr(app, "get_db", make_fake_db([]))  # no DB rows
    assert _auth("Bearer proxy-42") == 42
