from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
    id TEXT PRIMARY KEY,
    name TEXT,
    source_type TEXT,
    source_ref TEXT,
    workspace TEXT,
    commit_sha TEXT,
    languages TEXT,
    file_count INTEGER,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    repository_id TEXT,
    status TEXT,
    started_at TEXT,
    finished_at TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    seq INTEGER,
    type TEXT,
    node_id TEXT,
    payload TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events (run_id, seq);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs (started_at);
CREATE TABLE IF NOT EXISTS artifacts (
    run_id TEXT,
    kind TEXT,
    payload TEXT,
    PRIMARY KEY (run_id, kind)
);
CREATE TABLE IF NOT EXISTS node_cache (
    cache_key TEXT PRIMARY KEY,
    node_id TEXT,
    payload TEXT,
    created_at TEXT
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            # WAL lets the UI read progress while a run is writing; busy_timeout avoids "database is locked".
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def insert_repository(self, row: dict) -> None:
        self.execute(
            """
            INSERT INTO repositories
            (id, name, source_type, source_ref, workspace, commit_sha, languages, file_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row.get("name", ""),
                row.get("source_type", ""),
                row.get("source_ref", ""),
                row.get("workspace", ""),
                row.get("commit_sha", ""),
                row.get("languages", "[]"),
                row.get("file_count", 0),
                utcnow(),
            ),
        )

    def update_repository(self, repo_id: str, **fields: Any) -> None:
        allowed = {"name", "workspace", "commit_sha", "languages", "file_count"}
        parts = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            parts.append(f"{key} = ?")
            values.append(value)
        if not parts:
            return
        values.append(repo_id)
        self.execute(f"UPDATE repositories SET {', '.join(parts)} WHERE id = ?", tuple(values))

    def repository(self, repo_id: str) -> dict | None:
        rows = self.query("SELECT * FROM repositories WHERE id = ?", (repo_id,))
        return dict(rows[0]) if rows else None

    def insert_run(self, run_id: str, repository_id: str) -> None:
        self.execute(
            "INSERT INTO runs (id, repository_id, status, started_at, finished_at, error) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, repository_id, "QUEUED", utcnow(), None, None),
        )

    def update_run(self, run_id: str, status: str, error: str | None = None, finished: bool = False) -> None:
        if finished:
            self.execute(
                "UPDATE runs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                (status, error, utcnow(), run_id),
            )
        else:
            self.execute("UPDATE runs SET status = ?, error = ? WHERE id = ?", (status, error, run_id))

    def run(self, run_id: str) -> dict | None:
        rows = self.query("SELECT * FROM runs WHERE id = ?", (run_id,))
        return dict(rows[0]) if rows else None

    def expired_runs(self, keep: int) -> list[dict]:
        """Finished runs beyond the newest `keep`, with the workspace each one used."""
        rows = self.query(
            """
            SELECT runs.id AS run_id, runs.repository_id, repositories.workspace
            FROM runs JOIN repositories ON repositories.id = runs.repository_id
            WHERE runs.status IN ('COMPLETED', 'FAILED')
            ORDER BY runs.started_at DESC LIMIT -1 OFFSET ?
            """,
            (keep,),
        )
        return [dict(row) for row in rows]

    def delete_run(self, run_id: str, repository_id: str) -> None:
        with self._lock:
            for table in ("events", "artifacts"):
                self._conn.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
            self._conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            if not self._conn.execute("SELECT 1 FROM runs WHERE repository_id = ?", (repository_id,)).fetchone():
                self._conn.execute("DELETE FROM repositories WHERE id = ?", (repository_id,))
            self._conn.commit()

    def repository_ids(self) -> set[str]:
        return {row["id"] for row in self.query("SELECT id FROM repositories")}

    def trim_cache(self, keep: int) -> None:
        self.execute(
            "DELETE FROM node_cache WHERE cache_key NOT IN "
            "(SELECT cache_key FROM node_cache ORDER BY created_at DESC LIMIT ?)",
            (keep,),
        )

    def fail_interrupted(self, reason: str) -> int:
        """Close runs a previous process left unfinished, so clients stop waiting on them."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE runs SET status = 'FAILED', error = ?, finished_at = ? "
                "WHERE status IN ('QUEUED', 'RUNNING', 'VERIFYING')",
                (reason, utcnow()),
            )
            self._conn.commit()
            return cursor.rowcount

    def list_runs(self, limit: int = 20) -> list[dict]:
        rows = self.query(
            """
            SELECT runs.*, repositories.name AS repo_name, repositories.source_type, repositories.commit_sha
            FROM runs JOIN repositories ON repositories.id = runs.repository_id
            ORDER BY runs.started_at DESC LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def add_event(self, run_id: str, event_type: str, node_id: str | None, payload: dict) -> dict:
        with self._lock:
            current = self._conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?", (run_id,)).fetchone()
            seq = int(current[0])
            created = utcnow()
            self._conn.execute(
                "INSERT INTO events (run_id, seq, type, node_id, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, seq, event_type, node_id, json.dumps(payload), created),
            )
            self._conn.commit()
        return {"seq": seq, "run_id": run_id, "type": event_type, "node_id": node_id, "payload": payload, "created_at": created}

    def events_after(self, run_id: str, seq: int) -> list[dict]:
        rows = self.query(
            "SELECT seq, run_id, type, node_id, payload, created_at FROM events WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, seq),
        )
        events = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item["payload"] or "{}")
            events.append(item)
        return events

    def save_artifact(self, run_id: str, kind: str, payload: Any) -> None:
        encoded = json.dumps(payload)
        self.execute(
            """
            INSERT INTO artifacts (run_id, kind, payload) VALUES (?, ?, ?)
            ON CONFLICT(run_id, kind) DO UPDATE SET payload = excluded.payload
            """,
            (run_id, kind, encoded),
        )

    def artifact(self, run_id: str, kind: str) -> Any:
        rows = self.query("SELECT payload FROM artifacts WHERE run_id = ? AND kind = ?", (run_id, kind))
        if not rows:
            return None
        return json.loads(rows[0]["payload"])

    def cache_get(self, key: str) -> dict | None:
        rows = self.query("SELECT payload FROM node_cache WHERE cache_key = ?", (key,))
        if not rows:
            return None
        return json.loads(rows[0]["payload"])

    def cache_put(self, key: str, node_id: str, payload: dict) -> None:
        self.execute(
            """
            INSERT INTO node_cache (cache_key, node_id, payload, created_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET payload = excluded.payload, created_at = excluded.created_at
            """,
            (key, node_id, json.dumps(payload), utcnow()),
        )
