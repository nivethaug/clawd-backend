"""First-review bug fixes: command word-limit, stale repair payload,
planning recovery, create-retry reuse."""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import services.dev_cycles.engine as eng  # noqa: E402


class _StoreSpy:
    def __init__(self, tasks, cycle):
        self.tasks = [dict(t) for t in tasks]
        self.cycle = dict(cycle)
        self.updates = []
        self.said = []

    def get_tasks(self, _cid):
        return self.tasks

    def get_cycle(self, _cid):
        return self.cycle

    def update_task(self, tid, **fields):
        self.updates.append(("task", tid, fields))
        for t in self.tasks:
            if t["id"] == tid:
                t.update(fields)

    def update_cycle(self, _cid, **fields):
        self.updates.append(("cycle", fields))
        self.cycle.update(fields)

    def add_message(self, _cid, _role, content):
        self.said.append(content)


def _cycle(status="building", project_id=None):
    return {"id": 9, "status": status, "project_id": project_id,
            "user_id": 42, "plan": {}, "dod": [], "requirement_accum": "r",
            "evidence": None, "telegram_chat_id": None}


def _task(id=1, status="failed", kind="create", payload=None, repair_count=2):
    return {"id": id, "cycle_id": 9, "position": 0, "title": "Build it",
            "description": "the brief", "kind": kind,
            "status": status, "repair_count": repair_count,
            "result": '{"verdict": "fail"}',
            "payload": json.dumps(payload or {}),
            "session_run_id": None, "creation_run_id": 5,
            "dod_item": None}


def test_bug1_long_redo_is_correction_not_command(monkeypatch):
    spy = _StoreSpy([_task(status="done")], _cycle())
    monkeypatch.setattr(eng.store, "get_tasks", spy.get_tasks)
    monkeypatch.setattr(eng.store, "add_message", spy.add_message)
    monkeypatch.setattr(eng.store, "add_task", lambda *a, **k: None)
    monkeypatch.setattr(eng.store, "update_task", spy.update_task)
    monkeypatch.setattr(eng.store, "update_cycle", spy.update_cycle)
    monkeypatch.setattr(eng, "_dispatch_next", lambda _c: None)
    monkeypatch.setattr(eng.chat_agent, "patch_dod", lambda dod, text: dod)

    eng._handle_followup(_cycle(), "Redo the hero section in blue")
    # a correction was acknowledged — the request was NOT swallowed as retry
    assert spy.said, "no acknowledgement at all"
    assert not any("Nothing failed" in m for m in spy.said)


def test_bug1_short_retry_is_command(monkeypatch):
    spy = _StoreSpy([_task()], _cycle())
    monkeypatch.setattr(eng.store, "get_tasks", spy.get_tasks)
    monkeypatch.setattr(eng.store, "add_message", spy.add_message)
    monkeypatch.setattr(eng.store, "update_task", spy.update_task)
    monkeypatch.setattr(eng.store, "update_cycle", spy.update_cycle)
    monkeypatch.setattr(eng, "_dispatch_next", lambda _c: None)

    eng._handle_followup(_cycle(), "retry")
    assert any("On it — retrying" in s for s in spy.said)


def test_bug2_retry_clears_stale_repair_instruction(monkeypatch):
    t = _task(payload={"repair_instruction": "fix the old thing"})
    spy = _StoreSpy([t], _cycle())
    monkeypatch.setattr(eng.store, "get_tasks", spy.get_tasks)
    monkeypatch.setattr(eng.store, "add_message", spy.add_message)
    monkeypatch.setattr(eng.store, "update_task", spy.update_task)
    monkeypatch.setattr(eng.store, "update_cycle", spy.update_cycle)
    monkeypatch.setattr(eng, "_dispatch_next", lambda _c: None)

    eng._handle_followup(_cycle(), "retry")
    upd = next(u for u in spy.updates if u[0] == "task" and u[1] == t["id"])
    payload = json.loads(upd[2]["payload"])
    assert "repair_instruction" not in payload


def test_bug4_create_retry_becomes_instruct_when_project_exists(monkeypatch):
    t = _task(kind="create")
    spy = _StoreSpy([t], _cycle(project_id=321))
    monkeypatch.setattr(eng.store, "get_tasks", spy.get_tasks)
    monkeypatch.setattr(eng.store, "add_message", spy.add_message)
    monkeypatch.setattr(eng.store, "update_task", spy.update_task)
    monkeypatch.setattr(eng.store, "update_cycle", spy.update_cycle)
    monkeypatch.setattr(eng, "_dispatch_next", lambda _c: None)

    eng._handle_followup(_cycle(project_id=321), "retry")
    upd = next(u for u in spy.updates if u[0] == "task" and u[1] == t["id"])
    assert upd[2]["kind"] == "instruct"          # no second create
    assert json.loads(upd[2]["payload"]).get("create_retry") is True


def test_bug4_create_retry_stays_create_without_project(monkeypatch):
    t = _task(kind="create")
    spy = _StoreSpy([t], _cycle(project_id=None))
    monkeypatch.setattr(eng.store, "get_tasks", spy.get_tasks)
    monkeypatch.setattr(eng.store, "add_message", spy.add_message)
    monkeypatch.setattr(eng.store, "update_task", spy.update_task)
    monkeypatch.setattr(eng.store, "update_cycle", spy.update_cycle)
    monkeypatch.setattr(eng, "_dispatch_next", lambda _c: None)

    eng._handle_followup(_cycle(project_id=None), "retry")
    upd = next(u for u in spy.updates if u[0] == "task" and u[1] == t["id"])
    assert upd[2].get("kind", "create") == "create"  # nothing to reuse → recreate


def test_bug3_planning_message_not_dropped(monkeypatch):
    spy = _StoreSpy([], _cycle(status="planning"))
    monkeypatch.setattr(eng.store, "get_cycle", spy.get_cycle)
    monkeypatch.setattr(eng.store, "get_messages", lambda _c, limit=200: [
        {"id": 1, "role": "user", "content": "make it dark"}])
    monkeypatch.setattr(eng.store, "add_message", spy.add_message)
    monkeypatch.setattr(eng.store, "update_cycle", spy.update_cycle)
    monkeypatch.setattr(eng, "_dispatch_next", lambda _c: None)

    eng._on_user_message(9, message_id=1)
    assert any("Noted" in s for s in spy.said)          # acknowledged
    assert spy.cycle["status"] == "building"            # board recovered
