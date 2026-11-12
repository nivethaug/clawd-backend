"""T6: heartbeat watchdog + status-guarded mark_completed/mark_failed."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import services.session_chat_runs as scr  # noqa: E402


class _FakeResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


def _patch_db(monkeypatch, rowcount):
    from audit_conftest import make_fake_db
    db = make_fake_db([])
    db.conn.cursor_obj.rowcount = rowcount

    # record executed statements
    executed = []
    real_exec = db.conn.execute

    def rec(query, params=None):
        executed.append(query)
        return real_exec(query, params)

    db.conn.execute = rec
    monkeypatch.setattr(scr, "get_db", db)
    return executed


def test_t6_mark_completed_guards_terminal_states(monkeypatch):
    executed = _patch_db(monkeypatch, rowcount=1)
    scr.mark_completed(7, 99, {"total_tokens": 5}, True)
    assert any("status IN ('queued', 'running', 'cancel_requested')" in q for q in executed)


def test_t6_mark_completed_zero_rows_skips_notify(monkeypatch):
    _patch_db(monkeypatch, rowcount=0)
    notified = []
    import services.dev_cycles.notify as notify_mod
    monkeypatch.setattr(notify_mod, "notify_session_run",
                        lambda rid, st: notified.append((rid, st)))
    scr.mark_completed(7, 99, None, False)
    assert notified == []  # suppressed for already-finalized run


def test_t6_mark_failed_never_overwrites_completed(monkeypatch):
    executed = _patch_db(monkeypatch, rowcount=1)
    scr.mark_failed(7, "failed", "boom")
    assert any("status NOT IN ('completed')" in q for q in executed)


def test_t6_heartbeat_watchdog_ticks_while_silent(monkeypatch):
    """The watchdog must tick even when the streaming generator is silent."""
    ticks = []

    def fake_update_heartbeat(run_id):
        ticks.append(run_id)

    monkeypatch.setattr(scr, "update_heartbeat", fake_update_heartbeat)

    import acp_chat_handler

    class SlowHandler:
        project_name = "P"; project_path = "/p"; frontend_src_path = "/f"
        project_type_id = 1; bot_subdir = None

        def set_session_id(self, _s):
            pass

        def set_model(self, _m):
            pass

        def set_reasoning_effort(self, _e):
            pass

        async def run_chat_streaming_unified(self, _m, _c):
            # silent for ~0.35s — longer than two 15s ticks scaled down below
            await asyncio.sleep(0.35)
            yield "done"

        def get_last_token_usage(self):
            return {"output_tokens": 1}

        def kill_orphan_processes(self):
            pass

    monkeypatch.setattr(acp_chat_handler, "get_acp_chat_handler",
                        lambda _k: SlowHandler())

    run_row = {
        "id": 3, "session_id": 5, "project_id": 9, "session_key": "s1",
        "channel": "webchat", "image_attachment": None,
        "reserved_charges": "[]", "billing_user_id": None,
        "model": None, "reasoning_effort": None, "mode": "dream",
        "user_message": "hi", "session_context": "",
    }
    monkeypatch.setattr(scr, "get_run", lambda _rid: run_row)
    from audit_conftest import make_fake_db
    monkeypatch.setattr(scr, "get_db", make_fake_db([]))
    monkeypatch.setattr(scr, "is_cancel_requested", lambda _rid: False)
    monkeypatch.setattr(scr, "append_chunk", lambda *a, **k: None)
    monkeypatch.setattr(scr, "mark_completed", lambda *a, **k: None)
    monkeypatch.setattr(scr, "_release_project_lock_if_owner", lambda *a: None)
    monkeypatch.setattr(scr.SessionLockService, "release_processing",
                        staticmethod(lambda *a: None))

    import services.external_session_chat as ext

    async def _auto_commit(*a, **k):
        return None

    async def _finalize(**k):
        return None

    monkeypatch.setattr(ext, "auto_commit_selected_session_change", _auto_commit)
    monkeypatch.setattr(ext, "finalize_session_token_usage", _finalize)

    # speed the test up: shrink the watchdog interval by patching sleep scale
    real_sleep = asyncio.sleep

    async def fast_sleep(s):
        # watchdog sleeps are 15s; shrink THOSE to 0.05s. The generator's
        # short sleeps run real so the silent phase actually lasts.
        if s >= 15.0:
            await real_sleep(0.05)
        else:
            await real_sleep(s)

    import services.session_chat_runs as mod
    # patch asyncio.sleep only inside the watchdog by targeting the loop's
    # 15.0 literal indirectly: run with a stubbed module-level sleep is not
    # possible without editing code; instead shrink via monkeypatching
    # asyncio.sleep used in _heartbeat_loop (it closes over asyncio.sleep)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    result = asyncio.run(scr.execute_run(3))
    assert result["status"] == "success", result
    assert len(ticks) >= 2, f"watchdog did not tick during silent phase: {ticks}"
