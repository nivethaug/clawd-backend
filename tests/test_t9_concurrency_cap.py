"""T9: per-user concurrency cap in claim_next_run."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import services.session_chat_runs as scr  # noqa: E402


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def getconn(self):
        return self.conn

    def putconn(self, c):
        pass


class _FakeRawConn:
    """Raw psycopg2-style conn used by claim_next_run (cursor() + autocommit)."""

    def __init__(self):
        self.queries = []
        self.results = {"select": None}  # fetchone result for the SELECT
        self._fake_cur = _FakeRawCursor(self)

    def cursor(self, cursor_factory=None):
        return self._fake_cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _FakeRawCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        self._conn.queries.append((query, params))
        self._row = self._conn.results.get("select")

    def fetchone(self):
        return self._row

    def close(self):
        pass


def _run_claim(monkeypatch, running_count):
    raw = _FakeRawConn()
    # the SELECT returns None (nothing claimable) — we only inspect the query
    raw.results["select"] = None
    monkeypatch.setattr(scr, "get_connection_pool", lambda: _FakePool(raw))
    import services.worker_registry as wr
    monkeypatch.setattr(wr, "is_shared_node", lambda _n: True)
    result = scr.claim_next_run("worker-1", node_id=None)
    return raw.queries, result


def test_t9_claim_query_includes_per_user_cap(monkeypatch):
    queries, _ = _run_claim(monkeypatch, running_count=2)
    select_q = queries[0][0]
    assert "r2.status = 'running'" in select_q
    assert "SESSION" not in select_q  # param bound, not interpolated


def test_t9_cap_env_override(monkeypatch):
    monkeypatch.setenv("SESSION_RUN_MAX_PER_USER", "5")
    queries, _ = _run_claim(monkeypatch, running_count=2)
    # cap param is the 3rd bound parameter
    assert queries[0][1][2] == 5


def test_t9_default_cap_is_two(monkeypatch):
    monkeypatch.delenv("SESSION_RUN_MAX_PER_USER", raising=False)
    queries, _ = _run_claim(monkeypatch, running_count=2)
    assert queries[0][1][2] == 2


def test_t9_query_keeps_skip_locked_and_fifo(monkeypatch):
    queries, _ = _run_claim(monkeypatch, running_count=0)
    q = queries[0][0]
    assert "FOR UPDATE SKIP LOCKED" in q
    assert "ORDER BY created_at ASC, id ASC" in q
