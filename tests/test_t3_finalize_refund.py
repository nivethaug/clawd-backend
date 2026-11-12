"""T3: cancelled/failed runs finalize when work was done, refund otherwise."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402  (stubs DB before any backend import)

import services.session_chat_runs as scr  # noqa: E402
import services.external_session_chat as ext  # noqa: E402
import acp_chat_handler  # noqa: E402


class _FakeHandler:
    def __init__(self, usage):
        self._usage = usage
        self.session_id = None

    def set_session_id(self, _sid):
        pass

    async def run_chat_streaming_unified(self, _msg, _ctx):
        yield "chunk one"
        raise asyncio.CancelledError()

    def get_last_token_usage(self):
        return self._usage

    def kill_orphan_processes(self):
        pass


def _run(monkeypatch, usage):
    calls = {"finalize": 0, "refund": 0, "failed": None}

    run_row = {
        "id": 1, "session_id": 5, "project_id": 9, "session_key": "s1",
        "channel": "webchat", "image_attachment": None,
        "reserved_charges": '[{"credit_type":"monthly","amount":1}]',
        "billing_user_id": 42, "model": None, "reasoning_effort": None,
        "mode": "dream", "user_message": "hi", "session_context": "",
    }
    monkeypatch.setattr(scr, "get_run", lambda _rid: run_row)
    monkeypatch.setattr(scr, "is_cancel_requested", lambda _rid: False)
    monkeypatch.setattr(scr, "append_chunk", lambda *a, **k: None)
    monkeypatch.setattr(scr, "update_heartbeat", lambda _rid: None)
    monkeypatch.setattr(scr, "mark_failed",
                        lambda rid, status, err: calls.__setitem__("failed", status))
    monkeypatch.setattr(scr, "_release_project_lock_if_owner", lambda *a: None)
    monkeypatch.setattr(scr.SessionLockService, "release_processing",
                        staticmethod(lambda *a: None))

    monkeypatch.setattr(acp_chat_handler, "get_acp_chat_handler",
                        lambda _key: _FakeHandler(usage))

    def _finalize(**kw):
        calls["finalize"] += 1

    def _refund(*a, **kw):
        calls["refund"] += 1

    monkeypatch.setattr(ext, "finalize_session_token_usage", _finalize)
    monkeypatch.setattr(ext, "refund_session_chat_credits", _refund)

    result = asyncio.run(scr.execute_run(1))
    return calls, result


def test_t3_cancel_with_work_finalizes_no_refund(monkeypatch):
    usage = {"output_tokens": 500, "input_tokens": 1000, "has_writes": True}
    calls, result = _run(monkeypatch, usage)
    assert result["status"] == "cancelled"
    assert calls["finalize"] == 1
    assert calls["refund"] == 0
    assert calls["failed"] == "cancelled"


def test_t3_cancel_without_work_refunds(monkeypatch):
    calls, result = _run(monkeypatch, None)  # no usage recorded
    assert result["status"] == "cancelled"
    assert calls["refund"] == 1
    assert calls["finalize"] == 0


def test_t3_run_produced_work_helper():
    assert scr._run_produced_work(_FakeHandler({"output_tokens": 1})) is True
    assert scr._run_produced_work(_FakeHandler({"has_writes": True})) is True
    assert scr._run_produced_work(_FakeHandler(None)) is False
    assert scr._run_produced_work(_FakeHandler({"output_tokens": 0, "input_tokens": 0})) is False
    assert scr._run_produced_work(None) is False
