"""T8: early exits and completion release the project lock."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_conftest import app_module, FakeRow, make_fake_db  # noqa: E402

app = app_module


def _setup(monkeypatch, *, active_run=None, processing_ok=True, messages=None):
    import services.session_chat_runs as scr
    import services.billing_service as billing

    rows = [
        ("SELECT * FROM sessions WHERE session_key",
         [FakeRow(id=5, project_id=9, session_key="s1", archived=0)]),
        ("SELECT user_id FROM projects WHERE id", [FakeRow(user_id=42)]),
    ]
    monkeypatch.setattr(app, "get_db", make_fake_db(rows))
    monkeypatch.setattr(app, "_require_session_key_owner", lambda *a, **k: 42)
    monkeypatch.setattr(app, "_self_heal_project_lock", lambda *_a: True)
    monkeypatch.setattr(app, "_resolve_session_model",
                        lambda mid, uid=None: {"id": "m", "name": "M", "multiplier": 1})
    monkeypatch.setattr(app, "_resolve_reasoning_effort", lambda eff, uid=None: "low")

    released = {"processing": 0, "lock": 0}
    monkeypatch.setattr(app.SessionLockService, "acquire_lock",
                        staticmethod(lambda *a: {"success": True}))
    monkeypatch.setattr(app.SessionLockService, "acquire_processing",
                        staticmethod(lambda *a, **k: {"success": processing_ok}))
    monkeypatch.setattr(app.SessionLockService, "release_processing",
                        staticmethod(lambda *a: released.__setitem__("processing", released["processing"] + 1)))
    monkeypatch.setattr(app.SessionLockService, "release_lock",
                        staticmethod(lambda *a: released.__setitem__("lock", released["lock"] + 1)))
    monkeypatch.setattr(scr, "get_active_run_for_project", lambda *a, **k: active_run)
    monkeypatch.setattr(billing, "reserve_credits",
                        lambda *a, **k: {"success": True, "charged": [{"amount": 1}]})
    return released


def _post(client, msgs=None, stream=True):
    return client.post("/chat", json={
        "session_key": "s1", "stream": stream,
        "messages": msgs if msgs is not None else [{"role": "user", "content": "hi"}],
    })


def test_t8_no_user_message_releases_no_lock(monkeypatch):
    """Validation moved BEFORE acquire — a 400 must not even take the lock."""
    from fastapi.testclient import TestClient
    releases = _setup(monkeypatch)
    taken = []
    real_acquire = app.SessionLockService.acquire_lock
    monkeypatch.setattr(
        app.SessionLockService, "acquire_lock",
        staticmethod(lambda *a: (taken.append(1), {"success": True})[1]))
    client = TestClient(app.app)
    r = _post(client, msgs=[])
    assert r.status_code == 400
    assert taken == []            # lock never acquired
    assert releases["lock"] == 0  # nothing to release


def test_t8_other_active_run_409_releases_lock(monkeypatch):
    from fastapi.testclient import TestClient
    releases = _setup(monkeypatch, active_run={"session_id": 99})
    client = TestClient(app.app)
    r = _post(client)
    assert r.status_code == 409
    assert releases["lock"] == 1  # released before the raise


def test_t8_processing_conflict_409_releases_lock(monkeypatch):
    from fastapi.testclient import TestClient
    releases = _setup(monkeypatch, processing_ok=False)
    client = TestClient(app.app)
    r = _post(client)
    assert r.status_code == 409
    assert releases["lock"] == 1


def test_t8_nonstream_success_releases_lock(monkeypatch):
    from fastapi.testclient import TestClient
    import acp_chat_handler
    releases = _setup(monkeypatch)

    class H:
        project_name = "P"; project_path = "/p"; frontend_src_path = "/f"
        project_type_id = 1; bot_subdir = None

        def set_session_id(self, _s):
            pass

        def set_model(self, _m):
            pass

        def set_reasoning_effort(self, _e):
            pass

        def run_acpx_chat(self, c, ctx):
            return {"success": True, "response": "done", "status": "done"}

        def get_last_token_usage(self):
            return None

        def kill_orphan_processes(self):
            pass

    monkeypatch.setattr(acp_chat_handler, "get_acp_chat_handler", lambda _k: H())
    monkeypatch.setattr(app, "_load_session_context_budgeted", lambda *_a: "")
    client = TestClient(app.app)
    r = _post(client, stream=False, msgs=[{"role": "user", "content": "make a change"}])
    assert r.status_code == 200, r.text[:200]
    assert releases["lock"] >= 1      # released on completion (was leaked)
    assert releases["processing"] >= 1
