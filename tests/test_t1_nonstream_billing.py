"""T1: non-streaming /chat ACP branch — credit reservation + non-blocking run."""

import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_conftest import app_module, FakeRow, make_fake_db  # noqa: E402

app = app_module


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        return self.default(*a, **kw)


def _setup(monkeypatch, *, reserve_result=None, reserve_raises=False,
           acpx_thread_ids=None, acpx_raises=False):
    """Common fixture: fake DB, patched auth/locks/handler/billing."""
    import acp_chat_handler

    rows = [
        ("SELECT * FROM sessions WHERE session_key",
         [FakeRow(id=5, project_id=9, session_key="s1", archived=0)]),
        ("SELECT user_id FROM projects WHERE id",
         [FakeRow(user_id=42)]),
    ]
    fake_db = make_fake_db(rows)
    monkeypatch.setattr(app, "get_db", fake_db)
    monkeypatch.setattr(app, "_require_session_key_owner", lambda *_a, **_k: 42)
    monkeypatch.setattr(app, "_self_heal_project_lock", lambda *_a: True)
    monkeypatch.setattr(app, "_load_session_context_budgeted", lambda *_a: "")

    lock_calls = {"acquire": 0, "release_proc": 0}
    monkeypatch.setattr(
        app.SessionLockService, "acquire_lock",
        staticmethod(lambda *_a: {"success": True}))
    monkeypatch.setattr(
        app.SessionLockService, "acquire_processing",
        staticmethod(lambda *_a, **_k: {"success": True}))
    monkeypatch.setattr(
        app.SessionLockService, "release_processing",
        staticmethod(lambda *_a: lock_calls.__setitem__("release_proc", lock_calls["release_proc"] + 1)))

    class FakeHandler:
        def __init__(self):
            self.project_name = "P"
            self.project_path = "/tmp/p"
            self.frontend_src_path = "/tmp/p/frontend"
            self.project_type_id = 1
            self.bot_subdir = None

        def set_session_id(self, _sid):
            pass

        def get_last_token_usage(self):
            return None

        def kill_orphan_processes(self):
            pass

        def run_acpx_chat(self, content, ctx):
            if acpx_raises:
                raise RuntimeError("boom")
            if acpx_thread_ids is not None:
                acpx_thread_ids.append(threading.current_thread().ident)
            return {"success": True, "response": "done", "status": "done"}

    handler = FakeHandler()
    monkeypatch.setattr(acp_chat_handler, "get_acp_chat_handler",
                        lambda _key: handler)

    reserve_calls = []

    def fake_reserve(conn, user_id, op, amount=1):
        reserve_calls.append((user_id, op, amount))
        if reserve_raises:
            raise RuntimeError("billing down")
        return reserve_result if reserve_result is not None else {
            "success": True, "charged": [{"credit_type": "monthly", "amount": 1}]}

    import services.billing_service as billing
    monkeypatch.setattr(billing, "reserve_credits", fake_reserve)
    return {"reserve_calls": reserve_calls, "lock_calls": lock_calls,
            "handler": handler}


def _post(client, body=None):
    return client.post("/chat", json=body or {
        "session_key": "s1", "stream": False,
        "messages": [{"role": "user", "content": "make a change"}],
    })


def test_t1_zero_credits_402_and_agent_not_invoked(monkeypatch):
    from fastapi.testclient import TestClient
    f = _setup(monkeypatch, reserve_result={"success": False, "cost": 1,
                                            "total_available": 0})
    client = TestClient(app.app)
    r = _post(client)
    assert r.status_code == 402
    assert r.json()["detail"]["error"] == "insufficient_credits"
    assert len(f["reserve_calls"]) == 1
    # agent never ran (no ACPX call recorded — thread ids list untouched)
    assert "acpx_ran" not in f


def test_t1_funded_user_runs_off_event_loop(monkeypatch):
    from fastapi.testclient import TestClient
    thread_ids = []
    f = _setup(monkeypatch, acpx_thread_ids=thread_ids)
    client = TestClient(app.app)
    r = _post(client)
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "done"
    assert len(thread_ids) == 1
    # ran on a worker thread, not the event-loop thread
    assert thread_ids[0] != threading.current_thread().ident
    assert f["reserve_calls"] == [(42, "ADD_FEATURE", 1)]


def test_t1_billing_outage_503(monkeypatch):
    from fastapi.testclient import TestClient
    _setup(monkeypatch, reserve_raises=True)
    client = TestClient(app.app)
    r = _post(client)
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "billing_unavailable"
