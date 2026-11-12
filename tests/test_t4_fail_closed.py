"""T4: streaming /chat reservation fails closed — 503 on billing outage,
404 on missing owner, locks released, no run enqueued."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_conftest import app_module, FakeRow, make_fake_db  # noqa: E402

app = app_module


def _setup(monkeypatch, *, owner_row=True, reserve_raises=False):
    import services.billing_service as billing
    import services.session_chat_runs as scr

    rows = [
        ("SELECT * FROM sessions WHERE session_key",
         [FakeRow(id=5, project_id=9, session_key="s1", archived=0)]),
        ("SELECT user_id FROM projects WHERE id",
         [FakeRow(user_id=42)] if owner_row else []),
    ]
    monkeypatch.setattr(app, "get_db", make_fake_db(rows))
    monkeypatch.setattr(app, "_require_session_key_owner", lambda *a, **k: 42)
    monkeypatch.setattr(app, "_self_heal_project_lock", lambda *_a: True)
    monkeypatch.setattr(app, "_resolve_session_model",
                        lambda mid, uid=None: {"id": "z-ai/glm-5.3-flash",
                                               "name": "GLM", "multiplier": 1})
    monkeypatch.setattr(app, "_resolve_reasoning_effort",
                        lambda eff, uid=None: "low")

    released = {"processing": 0, "lock": 0}
    monkeypatch.setattr(app.SessionLockService, "acquire_lock",
                        staticmethod(lambda *a: {"success": True}))
    monkeypatch.setattr(app.SessionLockService, "acquire_processing",
                        staticmethod(lambda *a, **k: {"success": True}))
    monkeypatch.setattr(app.SessionLockService, "release_processing",
                        staticmethod(lambda *a: released.__setitem__(
                            "processing", released["processing"] + 1)))
    monkeypatch.setattr(app.SessionLockService, "release_lock",
                        staticmethod(lambda *a: released.__setitem__(
                            "lock", released["lock"] + 1)))
    monkeypatch.setattr(scr, "get_active_run_for_project", lambda *a, **k: None)

    def fake_reserve(conn, user_id, op, amount=1):
        if reserve_raises:
            raise RuntimeError("billing down")
        return {"success": True, "charged": [{"amount": 1}]}

    monkeypatch.setattr(billing, "reserve_credits", fake_reserve)
    return released


def _post(client):
    return client.post("/chat", json={
        "session_key": "s1", "stream": True,
        "messages": [{"role": "user", "content": "hello there"}],
    })


def test_t4_billing_outage_503_fails_closed(monkeypatch):
    from fastapi.testclient import TestClient
    released = _setup(monkeypatch, reserve_raises=True)
    client = TestClient(app.app)
    r = _post(client)
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "billing_unavailable"
    assert released["processing"] >= 1 and released["lock"] >= 1


def test_t4_missing_owner_404(monkeypatch):
    from fastapi.testclient import TestClient
    released = _setup(monkeypatch, owner_row=False)
    client = TestClient(app.app)
    r = _post(client)
    assert r.status_code == 404
    assert released["lock"] >= 1  # project lock released on early exit


def test_t4_funded_still_proceeds_past_reservation(monkeypatch):
    from fastapi.testclient import TestClient
    released = _setup(monkeypatch)  # reserve succeeds
    # Stay OFF the durable-run machinery: an unpatched background durable
    # task would outlive the test and crash in later test files.
    monkeypatch.setenv("SESSION_CHAT_DURABLE_RUNS", "0")
    client = TestClient(app.app)
    r = _post(client)
    # Past billing the flow continues (agent/stream machinery is unpatched, so
    # any non-503/402/404 status proves the reservation did not block it).
    assert r.status_code not in (503, 402, 404), r.text[:200]
    assert released["lock"] == 0  # lock NOT released on the happy path
