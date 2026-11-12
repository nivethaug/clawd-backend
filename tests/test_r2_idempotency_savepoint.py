"""R2: idempotency statements tolerate a missing table (savepoints)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import services.project_creation_runs as pcr  # noqa: E402


class _SavepointConn:
    """Fake conn: the idempotency table is MISSING — its statements raise
    (UndefinedTable). With savepoints, the transaction must keep working."""

    def __init__(self, replay_row=None, idem_insert_fails=True, table_present=False):
        self.replay_row = replay_row
        self.idem_insert_fails = idem_insert_fails
        self.table_present = table_present
        self.statements = []
        self._last = ""
        self.committed = 0
        self.rolled_back = 0
        self.savepoints = []

    def execute(self, query, params=None):
        q = query.strip().upper()
        self.statements.append(query)
        if q.startswith("SAVEPOINT"):
            self.savepoints.append(("save", query.split()[-1]))
        elif q.startswith("ROLLBACK TO SAVEPOINT"):
            self.savepoints.append(("rollback", query.split()[-1]))
        elif q.startswith("RELEASE SAVEPOINT"):
            self.savepoints.append(("release", query.split()[-1]))
        elif "FROM PROJECT_CREATE_IDEMPOTENCY" in q:
            self._last = "idem_replay"
            if not self.table_present and self.replay_row is None:
                raise RuntimeError('relation "project_create_idempotency" does not exist')
            self._last_row = self.replay_row
            return self
        elif "INSERT INTO PROJECT_CREATE_IDEMPOTENCY" in q:
            self._last = "idem_insert"
            if self.idem_insert_fails:
                raise RuntimeError('relation "project_create_idempotency" does not exist')
            return self
        elif q.startswith("INSERT INTO PROJECTS"):
            self._last = "project_insert"
            self._last_row = {"id": 5, "user_id": 42, "name": "n", "domain": "d",
                              "type_id": 1, "status": "creating"}
            return self
        else:
            self._last = "other"
            self._last_row = None
        return self

    def fetchone(self):
        return getattr(self, "_last_row", None)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


def _enqueue(conn, key="k1"):
    import contextlib

    @contextlib.contextmanager
    def _db():
        yield conn

    orig = pcr.get_db
    pcr.get_db = _db
    import services.worker_registry as wr
    orig_wr = wr.resolve_for_user
    wr.resolve_for_user = lambda _u: None
    try:
        return pcr.enqueue_project_creation_run(
            user_id=42, name="n", domain="d", description=None, type_id=1,
            template_id=None, bot_token=None, telegram_bot_token=None,
            telegram_chat_id=None, discord_webhook_url=None, email_to=None,
            api_endpoint=None, description_for_worker="x",
            idempotency_key=key)
    finally:
        pcr.get_db = orig
        wr.resolve_for_user = orig_wr


def test_r2_missing_table_create_still_succeeds():
    conn = _SavepointConn(replay_row=None, idem_insert_fails=True)
    project = _enqueue(conn, key="k1")
    assert project["id"] == 5                 # project created anyway
    assert conn.committed == 1                # transaction committed
    # replay probe failed → rolled back to savepoint, NOT a full rollback
    ops = conn.savepoints
    assert ("save", "idem_probe") in ops
    assert ("rollback", "idem_probe") in ops
    assert ("rollback", "idem_record") in ops  # upsert failed the same way
    assert conn.rolled_back == 0              # no full-transaction rollback


def test_r2_table_present_replay_returns_same_project():
    conn = _SavepointConn(
        replay_row={"id": 9, "user_id": 42, "name": "orig", "domain": "orig",
                    "type_id": 1, "status": "creating"},
        idem_insert_fails=False)
    project = _enqueue(conn, key="same-key")
    assert project["id"] == 9                 # replayed, not re-created
    assert ("release", "idem_probe") in conn.savepoints


def test_r2_upsert_success_releases_savepoint():
    conn = _SavepointConn(replay_row=None, idem_insert_fails=False, table_present=True)
    project = _enqueue(conn, key="k2")
    assert project["id"] == 5
    assert ("release", "idem_probe") in conn.savepoints
    assert ("release", "idem_record") in conn.savepoints
    assert conn.committed == 1
