"""R6: claim_next_run takes + re-checks under a per-user advisory lock."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import services.session_chat_runs as scr  # noqa: E402


class _RawCursor:
    def __init__(self, conn):
        self.c = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, q, p=None):
        self.c.queries.append((q.strip(), p))
        u = q.strip().upper()
        self._row = None
        if u.startswith("SELECT ID FROM SESSION_CHAT_RUNS"):
            self._row = {"id": 1}
        elif "SELECT BILLING_USER_ID FROM SESSION_CHAT_RUNS" in u:
            self._row = {"billing_user_id": 42}
        elif "SELECT COUNT(*)" in u and "RUNNING" in u:
            self._row = {"c": self.c.running_now}
        elif u.startswith("UPDATE SESSION_CHAT_RUNS") or ("SET STATUS = 'RUNNING'" in u):
            self.c.updates += 1
            self._row = {"id": 1, "status": "running", "worker_id": self.c.worker_id}
        return self

    def fetchone(self):
        return self._row


class _RawConn:
    def __init__(self, running_now, worker_id="worker-1"):
        self.queries = []
        self.running_now = running_now
        self.worker_id = worker_id
        self.committed = 0
        self.updates = 0

    def cursor(self, cursor_factory=None):
        return _RawCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass

    def close(self):
        pass


class _Pool:
    def __init__(self, c):
        self.c = c

    def getconn(self):
        return self.c

    def putconn(self, c):
        pass


def _claim(monkeypatch, running_now):
    conn = _RawConn(running_now)
    monkeypatch.setattr(scr, "get_connection_pool", lambda: _Pool(conn))
    import services.worker_registry as wr
    monkeypatch.setattr(wr, "is_shared_node", lambda _n: True)
    result = scr.claim_next_run("worker-1")
    return conn, result


def test_r6_at_cap_claim_returns_none_with_advisory_lock(monkeypatch):
    conn, result = _claim(monkeypatch, running_now=2)  # cap = 2 default
    assert result is None
    joined = "\n".join(q for q, _ in conn.queries)
    assert "pg_advisory_xact_lock" in joined
    assert "run_claim:" in joined
    assert conn.updates == 0        # nothing claimed
    assert conn.committed == 1      # xact ended → advisory lock released


def test_r6_under_cap_claim_proceeds(monkeypatch):
    conn, result = _claim(monkeypatch, running_now=1)
    assert result is not None       # claimed (claim_run builds a dict)
    assert conn.updates == 1
    assert conn.committed == 1      # lock released with the commit


def test_r6_claimed_dict_shape(monkeypatch):
    conn, result = _claim(monkeypatch, running_now=1)
    assert result["id"] == 1
    assert result["status"] == "running"
    assert result["worker_id"] == "worker-1"
