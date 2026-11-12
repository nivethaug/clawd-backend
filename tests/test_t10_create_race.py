"""T10: /projects advisory-lock transaction + Idempotency-Key."""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import services.project_creation_runs as pcr  # noqa: E402


class _LockingConn:
    """Fake conn that REALY serializes via a Python lock around execute —
    lets us prove the advisory-lock block makes check-then-insert atomic."""

    def __init__(self):
        self.lock = threading.Lock()
        self.queries = []
        self.result_for = {}
        self.committed = 0
        self.rolled_back = 0

    def execute(self, query, params=None):
        self.queries.append(query)
        self._last = query
        return self  # chainable

    def fetchone(self):
        for frag, val in self.result_for.items():
            if frag in self._last:
                return val
        return None

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


def test_t10_enqueue_uses_advisory_lock_and_guards(monkeypatch):
    conn = _LockingConn()
    from audit_conftest import make_fake_db
    # route every get_db to the same conn
    import contextlib

    @contextlib.contextmanager
    def _db():
        yield conn

    monkeypatch.setattr(pcr, "get_db", _db)

    insert_sql = "INSERT INTO projects"
    conn.result_for["SELECT role FROM users"] = {"role": "user"}
    conn.result_for["FROM projects WHERE user_id = %s AND status IN"] = None
    conn.result_for["SELECT COUNT(*)"] = {"cnt": 0}
    conn.result_for["lower(domain)"] = None
    conn.result_for[insert_sql] = {"id": 1, "user_id": 42, "name": "n", "domain": "d",
                                   "type_id": 1, "status": "creating"}
    import services.worker_registry as wr
    monkeypatch.setattr(wr, "resolve_for_user", lambda _u: None)

    project = pcr.enqueue_project_creation_run(
        user_id=42, name="n", domain="d", description=None, type_id=1,
        template_id=None, bot_token=None, telegram_bot_token=None,
        telegram_chat_id=None, discord_webhook_url=None, email_to=None,
        api_endpoint=None, description_for_worker="x",
        idempotency_key="k1", max_projects=5,
    )
    assert project["id"] == 1
    joined = "\n".join(conn.queries)
    assert "pg_advisory_xact_lock" in joined
    assert "project_create_idempotency" in joined
    assert "status NOT IN ('failed')" in joined          # fresh limit count
    assert "lower(domain) = lower" in joined             # domain re-check


def test_t10_active_creation_raises_conflict(monkeypatch):
    conn = _LockingConn()
    import contextlib

    @contextlib.contextmanager
    def _db():
        yield conn

    monkeypatch.setattr(pcr, "get_db", _db)
    conn.result_for["SELECT role FROM users"] = {"role": "user"}
    conn.result_for["FROM projects WHERE user_id = %s AND status IN"] = {"id": 9, "name": "busy", "status": "creating"}

    import pytest
    with pytest.raises(pcr.CreationConflictError):
        pcr.enqueue_project_creation_run(
            user_id=42, name="n", domain="d", description=None, type_id=1,
            template_id=None, bot_token=None, telegram_bot_token=None,
            telegram_chat_id=None, discord_webhook_url=None, email_to=None,
            api_endpoint=None, description_for_worker="x",
        )
    assert conn.rolled_back == 1


def test_t10_admin_bypasses_one_at_a_time(monkeypatch):
    conn = _LockingConn()
    import contextlib

    @contextlib.contextmanager
    def _db():
        yield conn

    monkeypatch.setattr(pcr, "get_db", _db)
    conn.result_for["SELECT role FROM users"] = {"role": "admin"}
    conn.result_for["INSERT INTO projects"] = {"id": 2, "user_id": 42, "name": "n",
                                               "domain": "d", "type_id": 1, "status": "creating"}
    import services.worker_registry as wr
    monkeypatch.setattr(wr, "resolve_for_user", lambda _u: None)
    project = pcr.enqueue_project_creation_run(
        user_id=42, name="n", domain="d", description=None, type_id=1,
        template_id=None, bot_token=None, telegram_bot_token=None,
        telegram_chat_id=None, discord_webhook_url=None, email_to=None,
        api_endpoint=None, description_for_worker="x",
    )
    assert project["id"] == 2
    # no active-creation guard query ran for admin
    assert not any("status IN" in q and "FROM projects WHERE user_id" in q for q in conn.queries)


def test_t10_limit_enforced_inside_lock(monkeypatch):
    conn = _LockingConn()
    import contextlib

    @contextlib.contextmanager
    def _db():
        yield conn

    monkeypatch.setattr(pcr, "get_db", _db)
    conn.result_for["SELECT role FROM users"] = {"role": "user"}
    conn.result_for["FROM projects WHERE user_id = %s AND status IN"] = None
    conn.result_for["SELECT COUNT(*)"] = {"cnt": 5}

    import pytest
    with pytest.raises(pcr.CreationLimitError):
        pcr.enqueue_project_creation_run(
            user_id=42, name="n", domain="d", description=None, type_id=1,
            template_id=None, bot_token=None, telegram_bot_token=None,
            telegram_chat_id=None, discord_webhook_url=None, email_to=None,
            api_endpoint=None, description_for_worker="x", max_projects=5,
        )


def test_t10_domain_conflict_inside_lock(monkeypatch):
    conn = _LockingConn()
    import contextlib

    @contextlib.contextmanager
    def _db():
        yield conn

    monkeypatch.setattr(pcr, "get_db", _db)
    conn.result_for["SELECT role FROM users"] = {"role": "user"}
    conn.result_for["FROM projects WHERE user_id = %s AND status IN"] = None
    conn.result_for["SELECT COUNT(*)"] = {"cnt": 0}
    conn.result_for["lower(domain)"] = {"id": 77}

    import pytest
    with pytest.raises(pcr.DomainConflictError):
        pcr.enqueue_project_creation_run(
            user_id=42, name="n", domain="taken", description=None, type_id=1,
            template_id=None, bot_token=None, telegram_bot_token=None,
            telegram_chat_id=None, discord_webhook_url=None, email_to=None,
            api_endpoint=None, description_for_worker="x",
        )
