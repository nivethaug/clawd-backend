"""T5: gate answers free only on the greeting/security path + rate limit."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_conftest import app_module, FakeRow, make_fake_db  # noqa: E402

app = app_module


def _setup(monkeypatch, *, gate_reply="I can't share internal details."):
    import services.billing_service as billing
    import services.session_chat_runs as scr

    rows = [
        ("SELECT * FROM sessions WHERE session_key",
         [FakeRow(id=5, project_id=9, session_key="s1", archived=0)]),
        ("SELECT user_id FROM projects WHERE id",
         [FakeRow(user_id=42)]),
    ]
    monkeypatch.setattr(app, "get_db", make_fake_db(rows))
    monkeypatch.setattr(app, "_require_session_key_owner", lambda *a, **k: 42)
    monkeypatch.setattr(app, "_self_heal_project_lock", lambda *_a: True)
    monkeypatch.setattr(app, "_resolve_session_model",
                        lambda mid, uid=None: {"id": "m", "name": "M", "multiplier": 1})
    monkeypatch.setattr(app, "_resolve_reasoning_effort",
                        lambda eff, uid=None: "low")
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
                        lambda *a, **k: {"success": True,
                                         "charged": [{"amount": 1}]})

    refunds = []

    def fake_refund(conn, user_id, op, charged):
        refunds.append(charged)

    monkeypatch.setattr(billing, "refund_credits", fake_refund)

    import acp_chat_handler
    monkeypatch.setattr(acp_chat_handler, "get_acp_chat_handler",
                        lambda _key: _GateHandler())
    monkeypatch.setattr(app, "check_message_gate", _make_gate(gate_reply))
    app._GATE_ANSWER_HITS.clear()
    return refunds


class _GateHandler:
    project_name = "P"
    project_path = "/tmp/p"
    frontend_src_path = "/tmp/p/f"
    project_type_id = 1
    bot_subdir = None

    def set_session_id(self, _s):
        pass

    def set_model(self, _m):
        pass

    def set_reasoning_effort(self, _e):
        pass


def _make_gate(reply):
    async def _gate(*a, **k):
        return reply
    return _gate


def _post(client, content):
    return client.post("/chat", json={
        "session_key": "s1", "stream": True,
        "messages": [{"role": "user", "content": content}],
    })


def test_t5_greeting_is_free_and_refunded(monkeypatch):
    from fastapi.testclient import TestClient
    refunds = _setup(monkeypatch)
    client = TestClient(app.app)
    r = _post(client, "hello")
    assert r.status_code == 200, r.text[:200]
    assert "Hi!" in r.text
    assert len(refunds) == 1  # reservation refunded on the free path


def test_t5_gate_answer_still_free_but_rate_limited(monkeypatch):
    from fastapi.testclient import TestClient
    _setup(monkeypatch)
    client = TestClient(app.app)
    statuses = []
    for i in range(app._GATE_ANSWER_LIMIT + 1):
        r = _post(client, "what model are you exactly")
        statuses.append(r.status_code)
    assert statuses[-1] == 429          # 21st gate answer within a minute
    assert statuses[0] == 200
    assert 429 not in statuses[:-1]
