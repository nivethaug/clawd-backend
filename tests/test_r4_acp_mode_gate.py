"""R4: acp_mode=false is rejected for non-admins on both endpoints."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_conftest import app_module, make_fake_db  # noqa: E402

app = app_module


def _setup(monkeypatch, *, is_admin=False):
    monkeypatch.setattr(app, "get_db", make_fake_db([]))
    monkeypatch.setattr(app, "_require_session_key_owner",
                        lambda _k, _a: 24 if is_admin else 42)
    monkeypatch.setattr(app, "_is_admin_user", lambda uid: uid == 24)
    openclaw_calls = []
    monkeypatch.setattr(app, "handle_chat_text_only",
                        lambda *a, **k: openclaw_calls.append(1) or "x")
    return openclaw_calls


def test_r4_stream_non_admin_400(monkeypatch):
    from fastapi.testclient import TestClient
    calls = _setup(monkeypatch, is_admin=False)
    client = TestClient(app.app)
    r = client.post("/chat", json={
        "session_key": "s1", "stream": True, "acp_mode": False,
        "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "acp_mode_required"
    assert calls == []  # LLM path never invoked


def test_r4_stream_admin_allowed(monkeypatch):
    from fastapi.testclient import TestClient
    _setup(monkeypatch, is_admin=True)
    client = TestClient(app.app)
    r = client.post("/chat", json={
        "session_key": "s1", "stream": True, "acp_mode": False,
        "messages": [{"role": "user", "content": "hi"}]})
    # admin passes the gate; downstream machinery unpatched → any non-400
    assert r.status_code != 400


def test_r4_nonstream_non_admin_400(monkeypatch):
    from fastapi.testclient import TestClient
    calls = _setup(monkeypatch, is_admin=False)
    client = TestClient(app.app)
    r = client.post("/chat", json={
        "session_key": "s1", "stream": False, "acp_mode": False,
        "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400
    assert calls == []


def test_r4_default_acp_mode_unchanged(monkeypatch):
    """Omitted acp_mode (default true) passes the gate for normal users."""
    from fastapi.testclient import TestClient
    import services.session_chat_runs as scr
    import services.billing_service as billing
    from audit_conftest import FakeRow, make_fake_db

    rows = [
        ("SELECT * FROM sessions WHERE session_key",
         [FakeRow(id=5, project_id=9, session_key="s1", archived=0)]),
        ("SELECT user_id FROM projects WHERE id", [FakeRow(user_id=42)]),
    ]
    monkeypatch.setattr(app, "get_db", make_fake_db(rows))
    monkeypatch.setattr(app, "_require_session_key_owner", lambda _k, _a: 42)
    monkeypatch.setattr(app, "_is_admin_user", lambda uid: False)
    monkeypatch.setattr(app, "_self_heal_project_lock", lambda *_a: True)
    monkeypatch.setattr(app, "_resolve_session_model",
                        lambda mid, uid=None: {"id": "m", "name": "M", "multiplier": 1})
    monkeypatch.setattr(app, "_resolve_reasoning_effort", lambda e, uid=None: "low")
    monkeypatch.setattr(app.SessionLockService, "acquire_lock",
                        staticmethod(lambda *a: {"success": True}))
    monkeypatch.setattr(app.SessionLockService, "acquire_processing",
                        staticmethod(lambda *a, **k: {"success": True}))
    monkeypatch.setattr(app.SessionLockService, "release_processing",
                        staticmethod(lambda *a: None))
    monkeypatch.setattr(app.SessionLockService, "release_lock",
                        staticmethod(lambda *a: None))
    monkeypatch.setattr(scr, "get_active_run_for_project", lambda *a, **k: None)
    monkeypatch.setattr(billing, "reserve_credits",
                        lambda *a, **k: {"success": True, "charged": [{"amount": 1}]})

    client = TestClient(app.app)
    r = client.post("/chat", json={  # no acp_mode field → default True
        "session_key": "s1", "stream": True,
        "messages": [{"role": "user", "content": "hello"}]})
    assert r.status_code != 400  # gate did not block the normal path
