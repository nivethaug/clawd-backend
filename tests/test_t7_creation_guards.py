"""T7: creation-run status guards + atomic charge record."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import services.project_creation_runs as pcr  # noqa: E402
from audit_conftest import make_fake_db  # noqa: E402


def _patch_db(monkeypatch, rowcount=1):
    db = make_fake_db([])
    db.conn.cursor_obj.rowcount = rowcount
    executed = []
    real_exec = db.conn.execute

    def rec(query, params=None):
        executed.append(query)
        return real_exec(query, params)

    db.conn.execute = rec
    monkeypatch.setattr(pcr, "get_db", db)
    return db, executed


def test_t7_mark_completed_guards_terminal(monkeypatch):
    monkeypatch.setattr(pcr, "prune_terminal_chunks", lambda **k: None)
    _db, executed = _patch_db(monkeypatch, rowcount=1)
    pcr.mark_completed(9, True)
    assert any("status NOT IN ('completed', 'failed', 'cancelled', 'interrupted')" in q
               for q in executed)


def test_t7_mark_completed_zero_rows_no_notify(monkeypatch):
    import services.dev_cycles.notify as notify_mod
    _patch_db(monkeypatch, rowcount=0)
    notified = []
    monkeypatch.setattr(pcr, "prune_terminal_chunks", lambda **k: None)
    monkeypatch.setattr(notify_mod, "notify_creation_run",
                        lambda *a, **k: notified.append(a))
    pcr.mark_completed(9)
    assert notified == []


def test_t7_mark_failed_never_overwrites_completed(monkeypatch):
    monkeypatch.setattr(pcr, "prune_terminal_chunks", lambda **k: None)
    _db, executed = _patch_db(monkeypatch, rowcount=1)
    pcr.mark_failed(9, "failed", "boom", project_id=3)
    assert any("status NOT IN ('completed')" in q for q in executed)


def test_t7_record_charge_joins_caller_transaction(monkeypatch):
    """With conn given, _record_charge must NOT open its own connection or
    commit — the charge and its record commit together with the caller."""
    db, _ = _patch_db(monkeypatch)
    own_db_calls = []
    real_get_db = pcr.get_db

    def counting_get_db():
        own_db_calls.append(1)
        return real_get_db()

    monkeypatch.setattr(pcr, "get_db", counting_get_db)
    pcr._record_charge(9, "WEBSITE", [{"amount": 1}], {"cost": 1}, conn=db.conn)
    # no extra connection opened, no commit issued by _record_charge itself
    assert own_db_calls == []
    assert db.conn.committed == 0


def test_t7_record_charge_standalone_still_commits(monkeypatch):
    db, _ = _patch_db(monkeypatch)
    pcr._record_charge(9, "WEBSITE", [{"amount": 1}], {"cost": 1})
    assert db.conn.committed == 1
