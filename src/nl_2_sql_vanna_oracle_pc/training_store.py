"""Durable source of truth for training review, memories, and audit history."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .settings import Settings

VALID_CANDIDATE_STATUSES = {"pending", "corrected", "approved", "rejected"}
VALID_MEMORY_STATUSES = {"active", "disabled", "sync_failed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrainingStore:
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
                CREATE TABLE IF NOT EXISTS training_candidates (
                    id TEXT PRIMARY KEY,
                    source_report_id TEXT UNIQUE,
                    conversation_id TEXT,
                    user_id TEXT,
                    question TEXT NOT NULL,
                    generated_sql TEXT NOT NULL,
                    corrected_sql TEXT,
                    answer TEXT,
                    request_success INTEGER,
                    request_error TEXT,
                    feedback TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewer_notes TEXT,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    test_status TEXT,
                    test_error TEXT,
                    last_tested_at TEXT,
                    memory_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_candidates_status
                    ON training_candidates(status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_candidates_conversation
                    ON training_candidates(conversation_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS training_memories (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    question TEXT,
                    sql TEXT,
                    content TEXT,
                    source_type TEXT NOT NULL,
                    source_candidate_id TEXT,
                    status TEXT NOT NULL,
                    approved_by TEXT,
                    chroma_memory_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(source_candidate_id) REFERENCES training_candidates(id)
                );

                CREATE INDEX IF NOT EXISTS idx_memories_status
                    ON training_memories(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS training_audit (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_training_audit_created
                    ON training_audit(created_at DESC);

                CREATE TABLE IF NOT EXISTS admin_sessions (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_admin_sessions_expiry
                    ON admin_sessions(expires_at);
                """
            )

    def create_admin_session(
        self, *, session_id: str, username: str, expires_at: int
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= ? OR revoked = 1",
                (int(datetime.now(timezone.utc).timestamp()),),
            )
            connection.execute(
                """
                INSERT INTO admin_sessions (
                    id, username, expires_at, revoked, created_at
                ) VALUES (?, ?, ?, 0, ?)
                """,
                (session_id, username, expires_at, utc_now()),
            )

    def is_admin_session_active(
        self, *, session_id: str, username: str, expires_at: int
    ) -> bool:
        now = int(datetime.now(timezone.utc).timestamp())
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM admin_sessions
                WHERE id = ? AND username = ? AND expires_at = ?
                  AND expires_at > ? AND revoked = 0
                """,
                (session_id, username, expires_at, now),
            ).fetchone()
        return row is not None

    def revoke_admin_session(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE admin_sessions SET revoked = 1 WHERE id = ?",
                (session_id,),
            )

    def ingest_report(self, report: dict[str, Any]) -> str | None:
        question = str(report.get("question") or "").strip()
        sql = str(report.get("generated_sql") or "").strip()
        report_id = str(report.get("report_id") or "").strip()
        if not question or not sql or not report_id:
            return None

        candidate_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nl2sql-report:{report_id}"))
        now = utc_now()
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                """
                SELECT id FROM training_candidates
                WHERE source_report_id IS NULL AND conversation_id = ?
                  AND question = ? AND generated_sql = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (str(report.get("conversation_id") or ""), question, sql),
            ).fetchone()
            if existing is not None:
                candidate_id = str(existing["id"])
                connection.execute(
                    """
                    UPDATE training_candidates
                    SET source_report_id = ?, answer = ?, request_success = ?,
                        request_error = ?
                    WHERE id = ?
                    """,
                    (
                        report_id,
                        report.get("answer"),
                        int(bool(report.get("success"))),
                        report.get("error"),
                        candidate_id,
                    ),
                )
                return candidate_id
            connection.execute(
                """
                INSERT INTO training_candidates (
                    id, source_report_id, conversation_id, user_id, question,
                    generated_sql, answer, request_success, request_error,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(source_report_id) DO UPDATE SET
                    answer = excluded.answer,
                    request_success = excluded.request_success,
                    request_error = excluded.request_error
                """,
                (
                    candidate_id,
                    report_id,
                    str(report.get("conversation_id") or ""),
                    str(report.get("user_id") or ""),
                    question,
                    sql,
                    report.get("answer"),
                    int(bool(report.get("success"))),
                    report.get("error"),
                    str(report.get("timestamp") or now),
                    now,
                ),
            )
        return candidate_id

    def create_manual_candidate(
        self, *, question: str, sql: str, actor: str, notes: str = ""
    ) -> str:
        candidate_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO training_candidates (
                    id, question, generated_sql, status, reviewer_notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (candidate_id, question.strip(), sql.strip(), notes.strip(), now, now),
            )
            self._audit(
                connection,
                actor=actor,
                action="candidate_created",
                entity_type="candidate",
                entity_id=candidate_id,
                details={"source": "manual"},
            )
        return candidate_id

    def record_feedback(
        self,
        *,
        conversation_id: str,
        question: str,
        sql: str,
        action: str,
        user_id: str,
        record_audit: bool = True,
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, feedback, corrected_sql, status
                FROM training_candidates
                WHERE conversation_id = ?
                  AND (generated_sql = ? OR question = ?)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (conversation_id, sql, question),
            ).fetchone()
            if row is None:
                if not question.strip() or not sql.strip():
                    return
                candidate_id = str(uuid.uuid4())
                status = "corrected" if action == "correct" else "pending"
                connection.execute(
                    """
                    INSERT INTO training_candidates (
                        id, conversation_id, user_id, question, generated_sql,
                        corrected_sql, feedback, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        conversation_id,
                        user_id,
                        question.strip(),
                        sql.strip(),
                        sql.strip() if action == "correct" else None,
                        action,
                        status,
                        now,
                        now,
                    ),
                )
                if record_audit:
                    self._audit(
                        connection,
                        actor=user_id,
                        action=f"feedback_{action}",
                        entity_type="candidate",
                        entity_id=candidate_id,
                        details={"source": "feedback"},
                    )
                return
            candidate_id = str(row["id"])
            corrected_sql = sql if action == "correct" else None
            next_status = "corrected" if action == "correct" else None
            if row["status"] in {"approved", "rejected"}:
                return
            if row["feedback"] == action and (
                action != "correct" or row["corrected_sql"] == corrected_sql
            ):
                return
            cursor = connection.execute(
                """
                UPDATE training_candidates
                SET feedback = ?,
                    corrected_sql = COALESCE(?, corrected_sql),
                    status = COALESCE(?, status),
                    updated_at = ?
                WHERE id = ? AND status NOT IN ('approved', 'rejected')
                """,
                (action, corrected_sql, next_status, now, candidate_id),
            )
            if cursor.rowcount and record_audit:
                self._audit(
                    connection,
                    actor=user_id,
                    action=f"feedback_{action}",
                    entity_type="candidate",
                    entity_id=candidate_id,
                    details={},
                )

    def list_candidates(
        self,
        *,
        status: str | None = None,
        feedback: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if status:
            if status not in VALID_CANDIDATE_STATUSES:
                raise ValueError("Invalid candidate status")
            conditions.append("status = ?")
            parameters.append(status)
        if feedback:
            conditions.append("feedback = ?")
            parameters.append(feedback)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._lock, self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM training_candidates {where}", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM training_candidates
                {where}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
        return {"total": total, "items": [dict(row) for row in rows]}

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM training_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
        return dict(row) if row else None

    def candidate_states_by_report(self, report_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        ids = [value for value in report_ids if value]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, source_report_id, status, feedback, memory_id
                FROM training_candidates
                WHERE source_report_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
        return {str(row["source_report_id"]): dict(row) for row in rows}

    def mark_test_result(
        self, candidate_id: str, *, success: bool, error: str | None
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE training_candidates
                SET test_status = ?, test_error = ?, last_tested_at = ?, updated_at = ?
                WHERE id = ?
                """,
                ("passed" if success else "failed", error, now, now, candidate_id),
            )

    def approve_candidate(
        self,
        *,
        candidate_id: str,
        sql: str,
        memory_id: str,
        actor: str,
        notes: str,
        metadata: dict[str, Any],
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            candidate = connection.execute(
                "SELECT question FROM training_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise KeyError(candidate_id)
            connection.execute(
                """
                INSERT INTO training_memories (
                    id, memory_type, question, sql, source_type,
                    source_candidate_id, status, approved_by, chroma_memory_id,
                    metadata_json, created_at, updated_at
                ) VALUES (?, 'tool', ?, ?, 'curated', ?, 'active', ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    question = excluded.question,
                    sql = excluded.sql,
                    status = 'active',
                    approved_by = excluded.approved_by,
                    chroma_memory_id = excluded.chroma_memory_id,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    memory_id,
                    str(candidate["question"]),
                    sql,
                    candidate_id,
                    actor,
                    memory_id,
                    json.dumps(metadata, separators=(",", ":"), ensure_ascii=False),
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE training_candidates
                SET corrected_sql = CASE
                        WHEN generated_sql <> ? THEN ? ELSE corrected_sql END,
                    status = 'approved', reviewer_notes = ?, reviewed_by = ?,
                    reviewed_at = ?, memory_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (sql, sql, notes.strip(), actor, now, memory_id, now, candidate_id),
            )
            self._audit(
                connection,
                actor=actor,
                action="candidate_approved",
                entity_type="candidate",
                entity_id=candidate_id,
                details={"memory_id": memory_id, "sql": sql},
            )

    def reject_candidate(self, candidate_id: str, *, actor: str, notes: str) -> bool:
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE training_candidates
                SET status = 'rejected', reviewer_notes = ?, reviewed_by = ?,
                    reviewed_at = ?, updated_at = ?
                WHERE id = ? AND status IN ('pending', 'corrected')
                """,
                (notes.strip(), actor, now, now, candidate_id),
            )
            if cursor.rowcount:
                self._audit(
                    connection,
                    actor=actor,
                    action="candidate_rejected",
                    entity_type="candidate",
                    entity_id=candidate_id,
                    details={"notes": notes.strip()},
                )
            return bool(cursor.rowcount)

    def find_active_duplicate(
        self, *, question: str, sql: str, exclude_candidate_id: str | None = None
    ) -> dict[str, Any] | None:
        normalized_question = " ".join(question.casefold().split())
        normalized_sql = " ".join(sql.casefold().split())
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM training_memories WHERE status = 'active' AND memory_type = 'tool'"
            ).fetchall()
        for row in rows:
            item = dict(row)
            if exclude_candidate_id and item.get("source_candidate_id") == exclude_candidate_id:
                continue
            if (
                " ".join(str(item.get("question") or "").casefold().split())
                == normalized_question
                and " ".join(str(item.get("sql") or "").casefold().split())
                == normalized_sql
            ):
                return item
        return None

    def list_memories(
        self, *, status: str | None = None, limit: int = 200, offset: int = 0
    ) -> dict[str, Any]:
        if status and status not in VALID_MEMORY_STATUSES:
            raise ValueError("Invalid memory status")
        where = "WHERE status = ?" if status else ""
        parameters: list[Any] = [status] if status else []
        with self._lock, self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM training_memories {where}", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM training_memories {where}
                ORDER BY updated_at DESC LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return {"total": total, "items": items}

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM training_memories WHERE id = ?", (memory_id,)
            ).fetchone()
        return dict(row) if row else None

    def disable_memory(self, memory_id: str, *, actor: str) -> bool:
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE training_memories SET status = 'disabled', updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (now, memory_id),
            )
            if cursor.rowcount:
                self._audit(
                    connection,
                    actor=actor,
                    action="memory_disabled",
                    entity_type="memory",
                    entity_id=memory_id,
                    details={},
                )
            return bool(cursor.rowcount)

    def enable_memory(self, memory_id: str, *, actor: str) -> bool:
        now = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE training_memories SET status = 'active', updated_at = ?
                WHERE id = ? AND status IN ('disabled', 'sync_failed')
                """,
                (now, memory_id),
            )
            if cursor.rowcount:
                self._audit(
                    connection,
                    actor=actor,
                    action="memory_enabled",
                    entity_type="memory",
                    entity_id=memory_id,
                    details={},
                )
            return bool(cursor.rowcount)

    def create_curated_text_memory(
        self, *, memory_id: str, content: str, actor: str
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO training_memories (
                    id, memory_type, content, source_type, status, approved_by,
                    chroma_memory_id, metadata_json, created_at, updated_at
                ) VALUES (?, 'text', ?, 'curated', 'active', ?, ?, '{}', ?, ?)
                """,
                (memory_id, content.strip(), actor, memory_id, now, now),
            )
            self._audit(
                connection,
                actor=actor,
                action="text_memory_created",
                entity_type="memory",
                entity_id=memory_id,
                details={},
            )

    def upsert_baseline_tool_memory(
        self, *, memory_id: str, question: str, sql: str
    ) -> None:
        self._upsert_baseline(
            memory_id=memory_id,
            memory_type="tool",
            question=question,
            sql=sql,
            content=None,
        )

    def upsert_baseline_text_memory(self, *, memory_id: str, content: str) -> None:
        self._upsert_baseline(
            memory_id=memory_id,
            memory_type="text",
            question=None,
            sql=None,
            content=content,
        )

    def _upsert_baseline(
        self,
        *,
        memory_id: str,
        memory_type: str,
        question: str | None,
        sql: str | None,
        content: str | None,
    ) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO training_memories (
                    id, memory_type, question, sql, content, source_type,
                    status, approved_by, chroma_memory_id, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'baseline', 'active', 'seed', ?, '{}', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    question = excluded.question,
                    sql = excluded.sql,
                    content = excluded.content,
                    status = 'active',
                    chroma_memory_id = excluded.chroma_memory_id,
                    updated_at = excluded.updated_at
                """,
                (
                    memory_id,
                    memory_type,
                    question,
                    sql,
                    content,
                    memory_id,
                    now,
                    now,
                ),
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM training_audit ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["details"] = json.loads(item.pop("details_json") or "{}")
        return items

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        details: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO training_audit (
                id, actor, action, entity_type, entity_id, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                actor,
                action,
                entity_type,
                entity_id,
                json.dumps(details, separators=(",", ":"), ensure_ascii=False),
                utc_now(),
            ),
        )


def create_training_store(settings: Settings) -> TrainingStore | None:
    if not settings.training_db_file:
        return None
    return TrainingStore(settings.training_db_file)
