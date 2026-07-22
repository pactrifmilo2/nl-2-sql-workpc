"""AI activity reporting and read-only report API."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import threading
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Query, status

from .settings import Settings

if TYPE_CHECKING:
    from .training_store import TrainingStore

logger = logging.getLogger(__name__)

DEFAULT_REPORT_LIMIT = 50
MAX_REPORT_LIMIT = 500


@dataclass
class ToolExecutionTrace:
    name: str
    success: bool
    execution_time_ms: float
    row_count: int | None = None
    error: str | None = None


@dataclass
class RequestTrace:
    request_id: str | None = None
    current_tool_name: str | None = None
    tool_executions: list[ToolExecutionTrace] = field(default_factory=list)
    chart_generated: bool = False


_request_trace_var: ContextVar[RequestTrace | None] = ContextVar(
    "ai_report_request_trace", default=None
)


def begin_request_trace() -> Token[RequestTrace | None]:
    return _request_trace_var.set(RequestTrace())


def get_request_trace() -> RequestTrace | None:
    return _request_trace_var.get()


def end_request_trace(token: Token[RequestTrace | None]) -> None:
    _request_trace_var.reset(token)


class AiReportLogger:
    """Append one privacy-controlled JSON record per user question."""

    def __init__(
        self,
        log_file_path: str | Path,
        training_store: TrainingStore | None = None,
    ) -> None:
        self.log_file = Path(log_file_path)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self.training_store = training_store

    def log(self, event: dict[str, Any]) -> None:
        try:
            line = json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
            with self._write_lock, self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except Exception as exc:
            logger.error("Failed to write AI report event: %s", exc, exc_info=True)
            return
        if self.training_store is not None:
            try:
                self.training_store.ingest_report(event)
            except Exception as exc:
                logger.error(
                    "Failed to create training candidate: %s", exc, exc_info=True
                )


def create_ai_report_logger(
    settings: Settings,
    training_store: TrainingStore | None = None,
) -> AiReportLogger | None:
    if not settings.ai_report_enabled or not settings.ai_report_log_file:
        return None
    return AiReportLogger(settings.ai_report_log_file, training_store)


def _sanitized_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    sensitive_fragments = (
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "credential",
        "authorization",
    )
    return {
        key: (
            "[REDACTED]"
            if any(fragment in key.lower() for fragment in sensitive_fragments)
            else value
        )
        for key, value in arguments.items()
    }


def build_request_report_event(
    *,
    settings: Settings,
    conversation: Any,
    conversation_id: str,
    user_id: str,
    question: str,
    started_at: datetime,
    duration_ms: float,
    trace: RequestTrace,
    processing_error: str | None,
) -> dict[str, Any]:
    messages = list(getattr(conversation, "messages", []) or [])
    question_index = -1
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if getattr(message, "role", None) == "user" and getattr(
            message, "content", ""
        ).strip() == question.strip():
            question_index = index
            break
    if question_index < 0:
        question_index = max(
            (
                index
                for index, message in enumerate(messages)
                if getattr(message, "role", None) == "user"
            ),
            default=len(messages) - 1,
        )

    answers: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    generated_sql: str | None = None
    for message in messages[question_index + 1 :]:
        role = getattr(message, "role", None)
        content = getattr(message, "content", "")
        if role == "assistant" and content:
            answers.append(content)
        if role != "assistant":
            continue
        for tool_call in getattr(message, "tool_calls", None) or []:
            arguments = _sanitized_arguments(dict(tool_call.arguments))
            tool_calls.append({"name": tool_call.name, "arguments": arguments})
            if tool_call.name == "run_sql" and isinstance(arguments.get("sql"), str):
                generated_sql = arguments["sql"]

    answer = "\n\n".join(answers) or None
    executions = [
        {
            "name": execution.name,
            "success": execution.success,
            "execution_time_ms": round(execution.execution_time_ms, 2),
            "row_count": execution.row_count,
            "error": execution.error,
        }
        for execution in trace.tool_executions
    ]
    failed_execution = next(
        (execution for execution in trace.tool_executions if not execution.success), None
    )
    success = processing_error is None and failed_execution is None
    sql_executions = [
        execution for execution in trace.tool_executions if execution.name == "run_sql"
    ]
    sql_execution_time_ms = (
        round(sum(execution.execution_time_ms for execution in sql_executions), 2)
        if sql_executions
        else None
    )
    rows_returned = (
        sum(execution.row_count or 0 for execution in sql_executions)
        if sql_executions
        else None
    )

    return {
        "report_id": new_report_id(),
        "timestamp": started_at.astimezone(timezone.utc).isoformat(),
        "request_id": trace.request_id,
        "conversation_id": conversation_id,
        "user_id": user_id,
        "model": settings.ollama_model,
        "question": question,
        "generated_sql": generated_sql,
        "answer": answer if settings.ai_report_include_response_text else None,
        "answer_length_chars": len(answer) if answer else 0,
        "tool_calls": tool_calls,
        "tool_executions": executions,
        "chart_generated": trace.chart_generated,
        "rows_returned": rows_returned,
        "duration_ms": round(duration_ms, 2),
        "sql_execution_time_ms": sql_execution_time_ms,
        "success": success,
        "error": processing_error
        or (failed_execution.error if failed_execution else None),
    }


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    log_path = Path(path)
    if not log_path.is_file():
        return []

    records: list[dict[str, Any]] = []
    try:
        with log_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "Skipping invalid JSONL record in %s at line %s",
                        log_path,
                        line_number,
                    )
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError as exc:
        logger.error("Failed to read report log %s: %s", log_path, exc)
    return records


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator * 100, 2)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    return round(ordered[index], 2)


def _feedback_by_report(
    feedback_records: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
]:
    by_sql: dict[tuple[str, str], dict[str, Any]] = {}
    by_question: dict[tuple[str, str], dict[str, Any]] = {}
    for record in feedback_records:
        conversation_id = str(record.get("conversation_id", ""))
        sql = str(record.get("sql", ""))
        question = str(record.get("question", ""))
        by_sql[(conversation_id, sql)] = record
        by_question[(conversation_id, question)] = record
    return by_sql, by_question


def build_ai_report(
    records: list[dict[str, Any]],
    feedback_records: list[dict[str, Any]],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    success: bool | None = None,
    user_id: str | None = None,
    limit: int = DEFAULT_REPORT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    feedback_by_sql, feedback_by_question = _feedback_by_report(feedback_records)
    filtered: list[dict[str, Any]] = []

    for original in records:
        record = dict(original)
        timestamp = _parse_timestamp(record.get("timestamp"))
        if start is not None and (timestamp is None or timestamp < start):
            continue
        if end is not None and (timestamp is None or timestamp >= end):
            continue
        if success is not None and record.get("success") is not success:
            continue
        if user_id is not None and record.get("user_id") != user_id:
            continue

        feedback = feedback_by_sql.get(
            (
                str(record.get("conversation_id", "")),
                str(record.get("generated_sql", "")),
            )
        )
        if feedback is None:
            feedback = feedback_by_question.get(
                (
                    str(record.get("conversation_id", "")),
                    str(record.get("question", "")),
                )
            )
        record["feedback"] = feedback.get("action") if feedback else None
        filtered.append(record)

    filtered.sort(key=lambda record: str(record.get("timestamp", "")), reverse=True)
    total = len(filtered)
    succeeded = sum(record.get("success") is True for record in filtered)
    failed = total - succeeded
    with_sql = sum(bool(record.get("generated_sql")) for record in filtered)
    durations = [
        float(record["duration_ms"])
        for record in filtered
        if isinstance(record.get("duration_ms"), (int, float))
    ]
    sql_durations = [
        float(record["sql_execution_time_ms"])
        for record in filtered
        if isinstance(record.get("sql_execution_time_ms"), (int, float))
    ]
    approvals = sum(record.get("feedback") == "approve" for record in filtered)
    rejections = sum(record.get("feedback") == "reject" for record in filtered)
    corrections = sum(record.get("feedback") == "correct" for record in filtered)
    reviewed = approvals + rejections + corrections

    items = filtered[offset : offset + limit]
    has_more = offset + limit < total
    return {
        "summary": {
            "total_requests": total,
            "successful_requests": succeeded,
            "failed_requests": failed,
            "success_rate_percent": _percent(succeeded, total),
            "average_duration_ms": _average(durations),
            "p95_duration_ms": _percentile_95(durations),
            "average_sql_execution_ms": _average(sql_durations),
            "requests_with_generated_sql": with_sql,
            "sql_generation_rate_percent": _percent(with_sql, total),
            "reviewed_requests": reviewed,
            "approved_requests": approvals,
            "rejected_requests": rejections,
            "corrected_requests": corrections,
            "approval_rate_percent": _percent(approvals, reviewed),
        },
        "items": items,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(items),
            "has_more": has_more,
            "next_offset": offset + limit if has_more else None,
        },
    }


def create_reports_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/reports", tags=["reports"])

    def require_api_key(x_api_key: str) -> None:
        if not settings.report_api_key:
            if settings.basic_auth_enabled:
                return
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Configure REPORT_API_KEY or application Basic Auth",
            )
        if not secrets.compare_digest(x_api_key, settings.report_api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid report API key",
            )

    @router.get("/ai")
    async def get_ai_report(
        start: datetime | None = None,
        end: datetime | None = None,
        success: bool | None = None,
        user_id: str | None = Query(default=None, max_length=320),
        limit: int = Query(default=DEFAULT_REPORT_LIMIT, ge=1, le=MAX_REPORT_LIMIT),
        offset: int = Query(default=0, ge=0),
        x_api_key: str = Header(default="", include_in_schema=False),
    ) -> dict[str, Any]:
        require_api_key(x_api_key)
        if start is not None and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start is not None and end is not None and start >= end:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="start must be earlier than end",
            )

        records, feedback_records = await asyncio.gather(
            asyncio.to_thread(_read_jsonl, settings.ai_report_log_file),
            asyncio.to_thread(_read_jsonl, settings.hitl_feedback_log_file),
        )
        return build_ai_report(
            records,
            feedback_records,
            start=start,
            end=end,
            success=success,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )

    @router.get("/ai/{report_id}")
    async def get_ai_report_item(
        report_id: str,
        x_api_key: str = Header(default="", include_in_schema=False),
    ) -> dict[str, Any]:
        require_api_key(x_api_key)
        records, feedback_records = await asyncio.gather(
            asyncio.to_thread(_read_jsonl, settings.ai_report_log_file),
            asyncio.to_thread(_read_jsonl, settings.hitl_feedback_log_file),
        )
        for record in reversed(records):
            if secrets.compare_digest(str(record.get("report_id", "")), report_id):
                report = build_ai_report([record], feedback_records, limit=1)
                return report["items"][0]
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    return router


def new_report_id() -> str:
    return str(uuid.uuid4())
