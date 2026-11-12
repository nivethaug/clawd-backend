"""R5: owner lookup failure fails closed (503), missing row 404."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_conftest import app_module, FakeRow, make_fake_db  # noqa: E402

app = app_module


def _setup(monkeypatch, *, owner_rows, owner_raises=False):
    import services.session_chat_runs as scr
    import services.billing_service as billing

    def route(q, p=None):
        if "SELECT user_id FROM projects" in q:
            if owner_raises:
                raise RuntimeError("db down")
            return owner_rows
        if "SELECT * FROM sessions WHERE session_key" in q:
            return [FakeRow(id=5, project_id=9, session_key="s1", archived=0)]
        return []

    monkeypatch.setattr(app, "get_db", make_fake_db(route))
    monkeypatch.setattr(app, "_require_session_key_owner", lambda _k, _a: 42)
    monkeypatch.setattr(app, "_self_heal_project_lock", lambda *_a: True)
    monkeypatch.setattr(app.SessionLockService, "acquire_lock",
                        staticmethod(lambda *a: {"success": True}))
    monkeypatch.setattr(app.SessionLockService, "acquire_processing",
                        staticmethod(lambda *a, **k: {"success": True}))
    released = {"lock": 0}
    monkeypatch.setattr(app.SessionLockService, "release_processing",
                        staticmethod(lambda *a: None))
    monkeypatch.setattr(app.SessionLockService, "release_lock",
                        staticmethod(lambda *a: released.__setitem__("lock", released["lock"] + 1)))
    monkeypatch.setattr(scr, "get_active_run_for_project", lambda *a, **k: None)
    monkeypatch.setattr(billing, "reserve_credits",
                        lambda *a, **k: {"success": True, "charged": []})
    monkeypatch.setenv("SESSION_CHAT_DURABLE_RUNS", "0")
    return released


def _post(client, model=None):
    body = {"session_key": "s1", "stream": True,
            "messages": [{"role": "user", "content": "hello there"}]}
    if model:
        body["model"] = model
    return client.post("/chat", json=body)


def test_r5_lookup_error_503_and_locks_released(monkeypatch):
    from fastapi.testclient import TestClient
    released = _setup(monkeypatch, owner_rows=[], owner_raises=True)
    client = TestClient(app.app)
    r = _post(client)
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "owner_lookup_failed"
    assert released["lock"] >= 1


def test_r5_missing_owner_404(monkeypatch):
    from fastapi.testclient import TestClient
    released = _setup(monkeypatch, owner_rows=[])
    client = TestClient(app.app)
    r = _post(client)
    assert r.status_code == 404
    assert released["lock"] >= 1


def test_r5_free_user_premium_model_still_clamped(monkeypatch):
    """Regression: with a real owner resolved, the tier gate clamps."""
    from fastapi.testclient import TestClient
    import services.rate_limiter as rl
    import services.session_chat_runs as scr
    import services.billing_service as billing

    def route(q, p=None):
        if "SELECT user_id FROM projects" in q:
            return [FakeRow(user_id=42)]
        if "SELECT * FROM sessions WHERE session_key" in q:
            return [FakeRow(id=5, project_id=9, session_key="s1", archived=0)]
        return []

    monkeypatch.setattr(app, "get_db", make_fake_db(route))
    monkeypatch.setattr(app, "_require_session_key_owner", lambda _k, _a: 42)
    monkeypatch.setattr(app, "_self_heal_project_lock", lambda *_a: True)
    monkeypatch.setattr(rl, "get_user_tier_and_role",
                        lambda uid: {"tier": "free", "role": "user"})
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
                        lambda *a, **k: {"success": True, "charged": []})
    monkeypatch.setenv("SESSION_CHAT_DURABLE_RUNS", "0")

    # spy on the resolver: premium model must be clamped for the free owner
    clamp_ok = []
    real = app._resolve_session_model

    def spy(model_id, user_id=None):
        info = real(model_id, user_id)
        if model_id == "z-ai/glm-5.3" and user_id == 42:
            clamp_ok.append(info.get("default") is True)
        return info

    monkeypatch.setattr(app, "_resolve_session_model", spy)
    client = TestClient(app.app)
    _post(client, model="z-ai/glm-5.3")  # premium model id explicitly
    assert clamp_ok and all(clamp_ok), "premium model was not clamped for free user"
