"""Shared harness for the audit-fix tests.

Importing app.py runs init_schema() (connects to Postgres). These tests run
offline: init_schema is stubbed BEFORE the app import, and every test that
hits a DB path monkeypatches app.get_db with a fake connection.

Usage in a test module:
    from tests.audit_conftest import app_module  # imports app offline
"""

import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("USE_POSTGRES", "true")

import database_adapter  # noqa: E402
import database_postgres  # noqa: E402


def _no_op(*_a, **_k):
    return None


# Stub schema init BEFORE app import so nothing connects at module level.
database_adapter.init_schema = _no_op
database_postgres.init_schema = _no_op
database_adapter.get_connection_pool = _no_op
database_postgres.get_connection_pool = _no_op


class FakeRow(dict):
    """Dict row that also supports tuple access (RealDict vs tuple duality)."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(dict.values(self))[key]
        return dict.__getitem__(self, key)


class FakeCursor:
    def __init__(self, results=None):
        # results: list of queries -> list[FakeRow] (or a callable(query, params))
        self.results = results or []
        self._queries = []

    def execute(self, query, params=None):
        self._queries.append((query, params))
        self._rows = self._resolve(query, params)

    def _resolve(self, query, params):
        if callable(self.results):
            return self.results(query, params)
        for q, rows in self.results:
            if q in query:
                return rows
        return []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def commit(self):
        pass

    def close(self):
        pass


class FakeConn:
    def __init__(self, results=None):
        self.cursor_obj = FakeCursor(results)
        self.committed = 0

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    # the app calls conn.execute(...).fetchone() directly (wrapper style):
    # return the cursor so chained fetch calls work.
    def execute(self, query, params=None):
        self.cursor_obj.execute(query, params)
        return self.cursor_obj

    def fetchone(self):
        return self.cursor_obj.fetchone()

    def fetchall(self):
        return self.cursor_obj.fetchall()

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass

    def close(self):
        pass


def make_fake_db(results=None):
    """Return a get_db replacement yielding one FakeConn."""
    conn = FakeConn(results)

    @contextmanager
    def _get_db():
        yield conn

    _get_db.conn = conn
    return _get_db


def _import_app():
    import importlib
    import app as app_module
    importlib.reload(app_module) if getattr(app_module, "__audit_reloaded__", False) else None
    return app_module


app_module = _import_app()
