"""S1: non-stream ACP /chat rejected for non-admins; admin path intact."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_conftest import app_module, make_fake_db  # noqa: E402

app = app_module


def _setup(monkeypatch, *, is_admin=False):
    import acp_chat_handler
    from audit_conftest import FakeRow

    rows = [
        ("SELECT * FROM sessions WHERE session_key",
         [FakeRow(id=5, project_id=9, session_key="s1", archived=0)]),
        ("SELECT user_id FROM projects WHERE id", [FakeRow(user_id=24 if is_admin else 42)]),
    ]
    monkeypatch.setattr(app, "get_db", make_fake_db(rows))
    monkeypatch.setattr(app, "_require_session_key_owner",
                        lambda _k, _a: 24 if is_admin else 42)
    monkeypatch.setattr(app, "_is_admin_user", lambda uid: uid == 24)

    acpx_calls = []

    class _H:
        project_name = "P"; project_path = "/p"; frontend_src_path = "/f"
        project_type_id = 1; bot_subdir = None

        def set_session_id(self, _s):
            pass

        def set_model(self, _m):
            pass

        def set_reasoning_effort(self, _e):
            pass

        def run_acpx_chat(self, c, ctx):
            acpx_calls.append(c)
            return {"success": True, "response": "done", "status": "done"}

        def get_last_token_usage(self):
            return None

        def kill_orphan_processes(self):
            pass

    monkeypatch.setattr(acp_chat_handler, "get_acp_chat_handler", lambda _k: _H())
    monkeypatch.setattr(app, "_load_session_context_budgeted", lambda *_a: "")

    import services.billing_service as billing
    import services.session_chat_runs as scr
    monkeypatch.setattr(billing, "reserve_credits",
                        lambda *a, **k: {"success": True, "charged": [{"amount": 1}]})
    monkeypatch.setattr(app.SessionLockService, "acquire_lock",
                        staticmethod(lambda *a: {"success": True}))
    monkeypatch.setattr(app.SessionLockService, "acquire_processing",
                        staticmethod(lambda *a, **k: {"success": True}))
    monkeypatch.setattr(app.SessionLockService, "release_processing",
                        staticmethod(lambda *a: None))
    monkeypatch.setattr(app.SessionLockService, "release_lock",
                        staticmethod(lambda *a: None))
    monkeypatch.setattr(scr, "get_active_run_for_project", lambda *a, **k: None)
    return acpx_calls


def _post(client, body):
    return client.post("/chat", json=body)


def test_s1_non_admin_non_stream_acp_400(monkeypatch):
    from fastapi.testclient import TestClient
    acpx = _setup(monkeypatch, is_admin=False)
    client = TestClient(app.app)
    r = _post(client, {"session_key": "s1", "stream": False, "acp_mode": True,
                       "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "stream_required"
    assert acpx == []  # the host-acpx path was never invoked


def test_s1_non_admin_stream_true_unchanged(monkeypatch):
    from fastapi.testclient import TestClient
    _setup(monkeypatch, is_admin=False)
    client = TestClient(app.app)
    r = _post(client, {"session_key": "s1", "stream": True, "acp_mode": True,
                       "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code != 400 or "stream_required" not in r.text


def test_s1_admin_non_stream_still_reaches_handler(monkeypatch):
    from fastapi.testclient import TestClient
    acpx = _setup(monkeypatch, is_admin=True)
    client = TestClient(app.app)
    r = _post(client, {"session_key": "s1", "stream": False, "acp_mode": True,
                       "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200, r.text[:200]
    assert acpx == ["hi"]  # admin bypasses the gate, handler ran
