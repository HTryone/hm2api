"""Private SQLite state for the Loomy gateway; currently the persisted admin session snapshot."""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
import sqlite3
import time
import warnings

MAX_BYTES = 16 * 1024 * 1024
NAMESPACES = ("sessions", "catalog")


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate state field")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("non-finite state value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _check_document(name, value):
    if name not in NAMESPACES or not isinstance(value, dict):
        raise ValueError("Invalid runtime state")
    if name == "catalog":
        if (set(value) != {"version", "models", "fetched_at"} or value.get("version") != 1
                or not isinstance(value.get("models"), dict)
                or type(value.get("fetched_at")) not in (int, float)):
            raise ValueError("Invalid model catalogue cache")
        if any(not isinstance(key, str) or not isinstance(row, dict) for key, row in value["models"].items()):
            raise ValueError("Invalid model catalogue entry")
        return
    if name == "sessions":
        from core.auth.admin_auth import _TOKEN, _FINGERPRINT, MAX_PERSISTED_SESSIONS
        if (set(value) != {"version", "fingerprint", "sessions"}
                or not isinstance(value.get("fingerprint"), str) or not _FINGERPRINT.fullmatch(value["fingerprint"])
                or len(value["sessions"]) > MAX_PERSISTED_SESSIONS):
            raise ValueError("Invalid session snapshot")
        for sid, row in value["sessions"].items():
            if (not isinstance(sid, str) or not _TOKEN.fullmatch(sid) or not isinstance(row, dict)
                    or set(row) != {"csrf_token", "expires"}
                    or not isinstance(row.get("csrf_token"), str) or not _TOKEN.fullmatch(row["csrf_token"])
                    or type(row.get("expires")) not in (int, float)
                    or not math.isfinite(row["expires"]) or not 0 < row["expires"] < 1e11):
                raise ValueError("Invalid persisted session")


class StateStore:
    """Share the control connection and lock without exposing secrets in public snapshots."""

    def __init__(self, control):
        self.control = control
        self.path = control.path
        self._db = control._db
        self._lock = control._lock

    @contextmanager
    def transaction(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise

    def _get(self, name):
        if name not in NAMESPACES:
            raise ValueError("Unknown state namespace")
        row = self._db.execute("SELECT payload FROM runtime_state WHERE name=?", (name,)).fetchone()
        if row is None:
            return None
        value = strict_json(row[0])
        _check_document(name, value)
        return value

    def get(self, name):
        with self._lock:
            return self._get(name)

    def _put(self, name, value):
        content = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        _check_document(name, value)
        if len(content.encode()) > MAX_BYTES:
            raise ValueError("Runtime state exceeds size limit")
        self._db.execute("INSERT INTO runtime_state(name,payload) VALUES(?,?) "
                         "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload", (name, content))

    def put(self, name, value):
        with self.transaction():
            self._put(name, value)

    def delete(self, name):
        if name not in NAMESPACES:
            raise ValueError("Unknown state namespace")
        with self.transaction():
            self._db.execute("DELETE FROM runtime_state WHERE name=?", (name,))


def note_cache_failure(name, error):
    warnings.warn(f"SQLite {name} cache write failed ({type(error).__name__}); keeping memory state",
                  RuntimeWarning, stacklevel=2)
