"""Persistent local evidence queue and independent reviewer assessments."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from .storage import canonical, digest


class ReviewStore:
    def __init__(self, root):
        self.path = root / "evidence.sqlite3"

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY, created TEXT NOT NULL, record TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assessments (
                evidence_id TEXT NOT NULL REFERENCES evidence(id),
                reviewer TEXT NOT NULL, verdict TEXT NOT NULL, note TEXT NOT NULL,
                updated TEXT NOT NULL, PRIMARY KEY (evidence_id, reviewer)
            );
        """)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def submit(self, record):
        # Created time and browser note IDs do not define the scientific evidence identity.
        identity = {key: value for key, value in record.items() if key not in {"id", "savedAt"}}
        key = digest(canonical(identity))
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO evidence VALUES (?, ?, ?)",
                (key, datetime.now(UTC).isoformat(), canonical(record)),
            )
        return key

    def assess(self, key, reviewer, verdict, note):
        with self.connect() as connection:
            if not connection.execute("SELECT 1 FROM evidence WHERE id=?", (key,)).fetchone():
                raise KeyError(key)
            connection.execute(
                """
                INSERT INTO assessments VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id, reviewer) DO UPDATE SET
                  verdict=excluded.verdict, note=excluded.note, updated=excluded.updated
            """,
                (key, reviewer, verdict, note, datetime.now(UTC).isoformat()),
            )

    def list(self):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, created, record FROM evidence ORDER BY created DESC LIMIT 100"
            ).fetchall()
            result = []
            for key, created, record in rows:
                votes = connection.execute(
                    "SELECT verdict, count(*) FROM assessments "
                    "WHERE evidence_id=? GROUP BY verdict",
                    (key,),
                ).fetchall()
                result.append(
                    {
                        "id": key,
                        "createdAt": created,
                        "record": json.loads(record),
                        "assessments": dict(votes),
                    }
                )
            return result

    def get(self, key):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT created, record FROM evidence WHERE id=?", (key,)
            ).fetchone()
            if row is None:
                raise KeyError(key)
            votes = connection.execute(
                "SELECT verdict, count(*) FROM assessments WHERE evidence_id=? GROUP BY verdict",
                (key,),
            ).fetchall()
            return {
                "id": key,
                "createdAt": row[0],
                "record": json.loads(row[1]),
                "assessments": dict(votes),
            }
