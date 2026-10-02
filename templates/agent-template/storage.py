"""Document storage for agent projects — NoSQL-style collections over SQLite.

One SQLite file per project (WAL mode). Documents are arbitrary JSON dicts
(schemaless bodies) inside an indexed envelope (_id, col, ts). Mongo-like API:

    from storage import db

    db.collection("checks").insert({"url": url, "status": "critical", "ms": 4200})
    db.collection("checks").find({"status": "critical"}, limit=50, sort="-ts")
    db.collection("stories").find_one({"url": story_url})
    db.collection("checks").count(since="24h")
    db.collection("checks").delete({"_id": doc_id})

    db.kv.set("last_run", "2026-01-01T08:00")   # convenience key-value
    db.kv.get("last_run")

Env:
    AGENT_DB  — db file path (default: <project root>/data/agent.db)

Notes:
- WAL mode: concurrent readers are safe; writes are serialized (fine for a
  single-agent, single-process workload).
- Equality filters match top-level document fields (via JSON1); `since`/
  `until` filter on the envelope `ts` (ISO strings compare correctly).
- Config files (feeds.json etc.) stay JSON — this store is for run data.
"""

import datetime
import json
import os
import sqlite3
import threading

__all__ = ["db", "Collection"]

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "agent.db"
)
_DB_PATH = os.getenv("AGENT_DB", _DEFAULT_PATH)

_init_lock = threading.Lock()
_write_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    with _init_lock:
        if _conn is None:
            os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
            _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _conn.execute(
                "CREATE TABLE IF NOT EXISTS docs ("
                " _id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " col TEXT NOT NULL,"
                " ts TEXT NOT NULL,"
                " data TEXT NOT NULL)"
            )
            _conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_col_ts ON docs (col, ts DESC)")
            _conn.commit()
        return _conn


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def _row_to_doc(row) -> dict:
    doc = json.loads(row["data"])
    doc["_id"] = row["_id"]
    doc["ts"] = row["ts"]
    return doc


class Collection:
    """Mongo-like document collection."""

    def __init__(self, name: str):
        self.name = name

    def insert(self, doc: dict) -> dict:
        """Insert a document (any JSON-serializable dict). Returns it with
        _id and ts set."""
        doc = dict(doc)
        ts = _now()
        conn = _connect()
        with _write_lock:
            cur = conn.execute(
                "INSERT INTO docs (col, ts, data) VALUES (?, ?, ?)",
                (self.name, ts, json.dumps(doc, default=str)),
            )
            conn.commit()
            doc["_id"] = cur.lastrowid
            doc["ts"] = ts
        return doc

    def find(
        self,
        filter: dict | None = None,
        limit: int = 50,
        sort: str = "-ts",
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict]:
        """Documents matching equality filters on top-level fields.
        sort: '-ts' (newest first, default) or 'ts'. since/until: ISO ts bounds."""
        conn = _connect()
        where, args = self._where(filter, since, until)
        order = "ts DESC" if str(sort).startswith("-") else "ts ASC"
        rows = conn.execute(
            f"SELECT * FROM docs WHERE col = ? {where} ORDER BY {order} LIMIT ?",
            (self.name, *args, max(1, int(limit))),
        ).fetchall()
        return [_row_to_doc(r) for r in rows]

    def find_one(self, filter: dict | None = None, **kw) -> dict | None:
        docs = self.find(filter, limit=1, **kw)
        return docs[0] if docs else None

    def count(self, filter: dict | None = None, since: str | None = None) -> int:
        conn = _connect()
        where, args = self._where(filter, since, None)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM docs WHERE col = ? {where}",
            (self.name, *args),
        ).fetchone()
        return row["n"]

    def update(self, filter: dict, patch: dict) -> int:
        """Merge `patch` into every matching document. Returns count updated."""
        conn = _connect()
        rows = self.find(filter, limit=1000)
        n = 0
        with _write_lock:
            for r in rows:
                merged = {k: v for k, v in r.items() if k not in ("_id", "ts")}
                merged.update(patch)
                conn.execute(
                    "UPDATE docs SET data = ? WHERE _id = ?",
                    (json.dumps(merged, default=str), r["_id"]),
                )
                n += 1
            conn.commit()
        return n

    def delete(self, filter: dict | None = None, older_than_days: int | None = None) -> int:
        """Delete matching documents. older_than_days prunes by ts instead."""
        conn = _connect()
        with _write_lock:
            if older_than_days is not None:
                cutoff = (
                    datetime.datetime.now(datetime.timezone.utc)
                    - datetime.timedelta(days=older_than_days)
                ).isoformat(timespec="milliseconds")
                cur = conn.execute(
                    "DELETE FROM docs WHERE col = ? AND ts < ?", (self.name, cutoff)
                )
            else:
                where, args = self._where(filter, None, None)
                cur = conn.execute(
                    f"DELETE FROM docs WHERE col = ? {where}", (self.name, *args)
                )
            conn.commit()
        return cur.rowcount

    @staticmethod
    def _where(filter: dict | None, since: str | None, until: str | None) -> tuple[str, list]:
        clauses, args = [], []
        f = filter or {}
        for k, v in f.items():
            if k in ("_id",):
                clauses.append("json_extract(data, '$._id') = ?")
                args.append(v)
                continue
            clauses.append(f"json_extract(data, {json.dumps('$.' + k)}) = ?")
            # strings compare raw (json_extract returns unquoted text);
            # bool/None via json.dumps to match JSON true/false/null
            args.append(v if isinstance(v, (int, float, bool)) or v is None else str(v))
        if since:
            clauses.append("ts >= ?")
            args.append(since)
        if until:
            clauses.append("ts <= ?")
            args.append(until)
        return ("AND " + " AND ".join(clauses)) if clauses else "", args


class _KV:
    """Convenience key-value store (a '_kv' collection)."""

    @staticmethod
    def set(key: str, value) -> None:
        col = db.collection("_kv")
        col.delete({"key": key})
        col.insert({"key": key, "value": value})

    @staticmethod
    def get(key: str, default=None):
        doc = db.collection("_kv").find_one({"key": key})
        return doc["value"] if doc else default


class _Database:
    """Entry point: db.collection(name) / db.kv."""

    def __init__(self):
        self._cols: dict[str, Collection] = {}

    def collection(self, name: str) -> Collection:
        if name not in self._cols:
            self._cols[name] = Collection(name)
        return self._cols[name]

    @property
    def kv(self) -> _KV:
        return _KV()


db = _Database()
