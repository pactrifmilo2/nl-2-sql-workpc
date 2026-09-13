"""Durable SQLite state for background queries and admin notifications."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


JOB_STATUSES = {"queued", "running", "succeeded", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    item["row_limit_reached"] = bool(item.get("row_limit_reached"))
    return item


class QueryJobStore:
    """Thread-safe durable queue designed for one or more local workers."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS query_jobs (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    conversation_id TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    question TEXT NOT NULL,
                    generated_sql TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
                    ),
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    row_count INTEGER,
                    column_count INTEGER,
                    row_limit_reached INTEGER NOT NULL DEFAULT 0,
                    result_file TEXT,
                    result_expires_at TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_query_jobs_status
                    ON query_jobs(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_query_jobs_requester
                    ON query_jobs(requested_by, created_at DESC);

                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    read_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES query_jobs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_notifications_recipient
                    ON notifications(recipient_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_notifications_unread
                    ON notifications(read_at, id DESC);
                """
            )

    def create_job(
        self,
        *,
        conversation_id: str,
        requested_by: str,
        question: str,
        sql: str,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        job_id = str(uuid.uuid4())
        with self._lock, self._connect() as connection:
            if idempotency_key:
                existing = connection.execute(
                    "SELECT * FROM query_jobs WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    return _as_dict(existing) or {}, False
            try:
                connection.execute(
                    """
                    INSERT INTO query_jobs (
                        id, idempotency_key, conversation_id, requested_by,
                        question, generated_sql, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (
                        job_id,
                        idempotency_key,
                        conversation_id,
                        requested_by,
                        question,
                        sql,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                if not idempotency_key:
                    raise
                existing = connection.execute(
                    "SELECT * FROM query_jobs WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing is None:
                    raise
                return _as_dict(existing) or {}, False
            row = connection.execute(
                "SELECT * FROM query_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return _as_dict(row) or {}, True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            return _as_dict(
                connection.execute(
                    "SELECT * FROM query_jobs WHERE id = ?", (job_id,)
                ).fetchone()
            )

    def list_jobs(
        self,
        *,
        status: str | None = None,
        requested_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if status is not None and status not in JOB_STATUSES:
            raise ValueError(f"Invalid job status: {status}")
        clauses: list[str] = []
        values: list[Any] = []
        if status:
            clauses.append("status = ?")
            values.append(status)
        if requested_by:
            clauses.append("requested_by = ?")
            values.append(requested_by)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock, self._connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM query_jobs{where}", values
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT * FROM query_jobs{where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                [*values, limit, offset],
            ).fetchall()
        items = [_as_dict(row) or {} for row in rows]
        return {
            "items": items,
            "total": total,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned": len(items),
                "has_more": offset + len(items) < total,
                "next_offset": offset + limit if offset + len(items) < total else None,
            },
        }

    def claim_next_job(self) -> dict[str, Any] | None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id FROM query_jobs
                WHERE status = 'queued' AND cancel_requested = 0
                ORDER BY created_at
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            job_id = str(row["id"])
            cursor = connection.execute(
                """
                UPDATE query_jobs
                SET status = 'running', started_at = ?, updated_at = ?,
                    attempt_count = attempt_count + 1
                WHERE id = ? AND status = 'queued' AND cancel_requested = 0
                """,
                (now, now, job_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            claimed = connection.execute(
                "SELECT * FROM query_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            return _as_dict(claimed)

    def requeue_interrupted_jobs(self) -> int:
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE query_jobs
                SET status = 'queued', started_at = NULL, updated_at = ?
                WHERE status = 'running' AND cancel_requested = 0
                """,
                (now,),
            )
            cancelled = connection.execute(
                "SELECT id, requested_by FROM query_jobs WHERE status = 'running' AND cancel_requested = 1"
            ).fetchall()
            for row in cancelled:
                self._set_cancelled(connection, str(row["id"]), str(row["requested_by"]), now)
            return cursor.rowcount

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM query_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return bool(row and row["cancel_requested"])

    def request_cancel(self, job_id: str) -> tuple[dict[str, Any] | None, bool]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM query_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None, False
            status = str(row["status"])
            accepted = False
            if status == "queued":
                self._set_cancelled(
                    connection, job_id, str(row["requested_by"]), now
                )
                accepted = True
            elif status == "running" and not row["cancel_requested"]:
                connection.execute(
                    """
                    UPDATE query_jobs
                    SET cancel_requested = 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, job_id),
                )
                accepted = True
            updated = connection.execute(
                "SELECT * FROM query_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return _as_dict(updated), accepted

    def complete_job(
        self,
        job_id: str,
        *,
        row_count: int,
        column_count: int,
        row_limit_reached: bool,
        result_file: str,
        result_expires_at: str,
    ) -> bool:
        now = utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT requested_by, cancel_requested FROM query_jobs WHERE id = ? AND status = 'running'",
                (job_id,),
            ).fetchone()
            if row is None or row["cancel_requested"]:
                return False
            cursor = connection.execute(
                """
                UPDATE query_jobs
                SET status = 'succeeded', row_count = ?, column_count = ?,
                    row_limit_reached = ?,
                    result_file = ?, result_expires_at = ?, error = NULL,
                    completed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running' AND cancel_requested = 0
                """,
                (
                    row_count,
                    column_count,
                    int(row_limit_reached),
                    result_file,
                    result_expires_at,
                    now,
                    now,
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._notify(
                connection,
                job_id=job_id,
                recipient_id=str(row["requested_by"]),
                notification_type="query.completed",
                title="Truy vấn đã hoàn thành",
                message=(
                    f"Truy vấn trả về {row_count} dòng"
                    + (
                        " và đã đạt giới hạn kết quả."
                        if row_limit_reached
                        else "."
                    )
                ),
                now=now,
            )
            return True

    def fail_job(self, job_id: str, error: str) -> bool:
        now = utc_now()
        safe_error = " ".join(error.split())[:4000] or "Unknown background query error"
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT requested_by, cancel_requested FROM query_jobs WHERE id = ? AND status = 'running'",
                (job_id,),
            ).fetchone()
            if row is None:
                return False
            if row["cancel_requested"]:
                self._set_cancelled(
                    connection, job_id, str(row["requested_by"]), now
                )
                return True
            connection.execute(
                """
                UPDATE query_jobs
                SET status = 'failed', error = ?, completed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (safe_error, now, now, job_id),
            )
            self._notify(
                connection,
                job_id=job_id,
                recipient_id=str(row["requested_by"]),
                notification_type="query.failed",
                title="Truy vấn nền thất bại",
                message=safe_error,
                now=now,
            )
            return True

    def finish_cancelled(self, job_id: str) -> bool:
        now = utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT requested_by FROM query_jobs WHERE id = ? AND status IN ('queued', 'running')",
                (job_id,),
            ).fetchone()
            if row is None:
                return False
            self._set_cancelled(
                connection, job_id, str(row["requested_by"]), now
            )
            return True

    def list_notifications(
        self,
        *,
        after_id: int = 0,
        unread_only: bool = False,
        recipient_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        clauses = ["id > ?"]
        values: list[Any] = [after_id]
        if unread_only:
            clauses.append("read_at IS NULL")
        if recipient_id:
            clauses.append("recipient_id = ?")
            values.append(recipient_id)
        where = " AND ".join(clauses)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM notifications
                WHERE {where}
                ORDER BY id
                LIMIT ?
                """,
                [*values, limit],
            ).fetchall()
            unread_count_query = (
                "SELECT COUNT(*) FROM notifications WHERE read_at IS NULL"
            )
            unread_count_values: list[Any] = []
            if recipient_id:
                unread_count_query += " AND recipient_id = ?"
                unread_count_values.append(recipient_id)
            unread_count = int(
                connection.execute(
                    unread_count_query, unread_count_values
                ).fetchone()[0]
            )
        items = [dict(row) for row in rows]
        return {
            "items": items,
            "unread_count": unread_count,
            "last_id": items[-1]["id"] if items else after_id,
        }

    def mark_notification_read(self, notification_id: int) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM notifications WHERE id = ?", (notification_id,)
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                "UPDATE notifications SET read_at = COALESCE(read_at, ?) WHERE id = ?",
                (utc_now(), notification_id),
            )
            return True

    def expire_result_files(self, *, now: str | None = None) -> list[str]:
        cutoff = now or utc_now()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT result_file FROM query_jobs
                WHERE result_file IS NOT NULL
                  AND result_expires_at IS NOT NULL
                  AND result_expires_at <= ?
                """,
                (cutoff,),
            ).fetchall()
            files = [str(row["result_file"]) for row in rows]
            if files:
                connection.execute(
                    """
                    UPDATE query_jobs
                    SET result_file = NULL, updated_at = ?
                    WHERE result_file IS NOT NULL
                      AND result_expires_at IS NOT NULL
                      AND result_expires_at <= ?
                    """,
                    (cutoff, cutoff),
                )
            return files

    def _set_cancelled(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        requested_by: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            UPDATE query_jobs
            SET status = 'cancelled', cancel_requested = 1,
                completed_at = ?, updated_at = ?
            WHERE id = ? AND status IN ('queued', 'running')
            """,
            (now, now, job_id),
        )
        self._notify(
            connection,
            job_id=job_id,
            recipient_id=requested_by,
            notification_type="query.cancelled",
            title="Truy vấn nền đã hủy",
            message="Yêu cầu chạy nền đã được hủy.",
            now=now,
        )

    @staticmethod
    def _notify(
        connection: sqlite3.Connection,
        *,
        job_id: str,
        recipient_id: str,
        notification_type: str,
        title: str,
        message: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO notifications (
                job_id, recipient_id, type, title, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_id, recipient_id, notification_type, title, message, now),
        )
