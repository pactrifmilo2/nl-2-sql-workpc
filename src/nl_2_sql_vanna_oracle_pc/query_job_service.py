"""Background query queue, worker, result persistence, and chat tool."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.components import CardComponent, SimpleTextComponent, UiComponent
from vanna.core.tool import Tool, ToolContext, ToolResult
from vanna.core.user import User

from .query_job_store import QueryJobStore
from .query_policy import validate_runtime_sql
from .settings import Settings

logger = logging.getLogger(__name__)


class QueueBackgroundSqlArgs(BaseModel):
    question: str = Field(
        min_length=3,
        max_length=4000,
        description="The user's complete Vietnamese data question.",
    )
    sql: str = Field(
        min_length=6,
        max_length=50_000,
        description="One read-only Oracle SELECT query for the request.",
    )

    @field_validator("question", "sql")
    @classmethod
    def strip_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class QueryJobService:
    """Own the durable queue and a single daemon worker thread."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: QueryJobStore,
        sql_runner: SqlRunner,
    ) -> None:
        self.settings = settings
        self.store = store
        self.sql_runner = sql_runner
        self.result_directory = Path(settings.query_job_result_directory)
        self.result_directory.mkdir(parents=True, exist_ok=True)
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_cleanup_at = 0.0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        recovered = self.store.requeue_interrupted_jobs()
        if recovered:
            logger.warning("Recovered %d interrupted background query job(s)", recovered)
        self._delete_expired_results(force=True)
        for temporary_path in self.result_directory.glob("*.tmp"):
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    "Could not delete abandoned query result: %s", temporary_path
                )
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="nl2sql-query-job-worker",
            daemon=True,
        )
        self._thread.start()
        logger.info("Background query worker started")

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning(
                    "Background query worker is still finishing an Oracle call during shutdown"
                )
            else:
                self._thread = None

    def enqueue(
        self,
        *,
        conversation_id: str,
        requested_by: str,
        question: str,
        sql: str,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, object], bool]:
        validated = validate_runtime_sql(sql, self.settings)
        job, created = self.store.create_job(
            conversation_id=conversation_id,
            requested_by=requested_by,
            question=question.strip(),
            sql=validated.sql,
            idempotency_key=idempotency_key,
        )
        self._wake_event.set()
        return job, created

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._delete_expired_results()
                job = self.store.claim_next_job()
                if job is not None:
                    self._execute_job(job)
                    continue
            except Exception:
                logger.exception("Background query worker loop failed")
            if not self._stop_event.is_set():
                self._wake_event.wait(self.settings.query_job_poll_seconds)
                self._wake_event.clear()

    def _execute_job(self, job: dict[str, object]) -> None:
        job_id = str(job["id"])
        result_path: Path | None = None
        temporary_path: Path | None = None
        try:
            context = ToolContext.model_construct(
                user=User(
                    id=str(job["requested_by"]),
                    group_memberships=["user"],
                ),
                conversation_id=str(job["conversation_id"]),
                request_id=job_id,
                agent_memory=None,
                metadata={"background_query": True},
            )
            dataframe = asyncio.run(
                self.sql_runner.run_sql(
                    RunSqlToolArgs(sql=str(job["generated_sql"])),
                    context,
                )
            )
            if self.store.is_cancel_requested(job_id):
                self.store.finish_cancelled(job_id)
                return

            result_path = self.result_directory / f"{job_id}.json.gz"
            temporary_path = Path(f"{result_path}.tmp")
            rows = json.loads(
                dataframe.to_json(
                    orient="records",
                    date_format="iso",
                    force_ascii=False,
                )
            )
            payload = {
                "job_id": job_id,
                "columns": [str(column) for column in dataframe.columns],
                "row_count": len(dataframe),
                "row_limit_reached": len(dataframe)
                >= self.settings.query_job_max_rows,
                "rows": rows,
            }
            with gzip.open(temporary_path, "wt", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            os.replace(temporary_path, result_path)

            expires_at = (
                datetime.now(timezone.utc)
                + timedelta(hours=self.settings.query_job_result_ttl_hours)
            ).isoformat()
            completed = self.store.complete_job(
                job_id,
                row_count=len(dataframe),
                column_count=len(dataframe.columns),
                row_limit_reached=len(dataframe)
                >= self.settings.query_job_max_rows,
                result_file=result_path.name,
                result_expires_at=expires_at,
            )
            if not completed:
                result_path.unlink(missing_ok=True)
                self.store.finish_cancelled(job_id)
        except Exception as exc:
            logger.exception("Background query job failed: job_id=%s", job_id)
            if result_path is not None:
                result_path.unlink(missing_ok=True)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            self.store.fail_job(job_id, str(exc))

    def _delete_expired_results(self, *, force: bool = False) -> None:
        current = time.monotonic()
        if not force and current < self._next_cleanup_at:
            return
        self._next_cleanup_at = current + 60
        for filename in self.store.expire_result_files():
            candidate = self.result_directory / Path(filename).name
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not delete expired query result: %s", candidate)


class QueueBackgroundSqlTool(Tool[QueueBackgroundSqlArgs]):
    """Queue a user-approved query and immediately return its durable job id."""

    def __init__(self, service: QueryJobService):
        self.service = service

    @property
    def name(self) -> str:
        return "queue_background_sql"

    @property
    def description(self) -> str:
        return (
            "Queue one validated read-only Oracle SQL query for background execution. "
            "Use by default for clear flight-data questions when background jobs are "
            "enabled. Do not use for unresolved ambiguities or interactive charts."
        )

    def get_args_schema(self) -> type[QueueBackgroundSqlArgs]:
        return QueueBackgroundSqlArgs

    async def execute(
        self,
        context: ToolContext,
        args: QueueBackgroundSqlArgs,
    ) -> ToolResult:
        idempotency_key = f"{context.conversation_id}:{context.request_id}"
        job, created = self.service.enqueue(
            conversation_id=context.conversation_id,
            requested_by=context.user.id,
            question=args.question,
            sql=args.sql,
            idempotency_key=idempotency_key,
        )
        job_id = str(job["id"])
        status = str(job["status"])
        if created:
            message = (
                f"Đã đưa truy vấn vào hàng chờ. Mã công việc: `{job_id}`. "
                "Bạn có thể theo dõi trạng thái trên trang quản trị."
            )
        else:
            message = (
                f"Yêu cầu này đã có công việc `{job_id}` với trạng thái `{status}`. "
                "Hệ thống không tạo công việc trùng lặp."
            )
        result_for_llm = (
            f"Background query job {job_id} has status {status}. "
            "Report that status in Vietnamese and explain that the admin page will "
            "receive a notification when execution finishes. Do not run SQL again."
        )
        return ToolResult(
            success=True,
            result_for_llm=result_for_llm,
            ui_component=UiComponent(
                rich_component=CardComponent(
                    title="Truy vấn đang chạy nền",
                    content=message,
                    icon="⏳",
                    status="info",
                    markdown=True,
                ),
                simple_component=SimpleTextComponent(text=message),
            ),
            metadata={
                "job_id": job_id,
                "job_status": status,
                "created": created,
            },
        )
