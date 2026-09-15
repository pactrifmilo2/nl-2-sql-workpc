from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user import User

from nl_2_sql_vanna_oracle_pc.auth_middleware import BasicAuthMiddleware
from nl_2_sql_vanna_oracle_pc.query_job_api import create_query_job_router
from nl_2_sql_vanna_oracle_pc.query_job_service import (
    QueryJobService,
    QueueBackgroundSqlArgs,
    QueueBackgroundSqlTool,
)
from nl_2_sql_vanna_oracle_pc.query_job_store import QueryJobStore
from nl_2_sql_vanna_oracle_pc.query_policy import QueryPolicyError
from nl_2_sql_vanna_oracle_pc.settings import Settings


def job_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values = {
        "oracle_user": "user",
        "oracle_password": "password",
        "oracle_dsn": "database",
        "allowed_tables": {"T_DAY_FLIGHTS", "T_FINISHED_FLIGHTS"},
        "allowed_columns": {"FLIGHTNBR", "FROM_AIRP", "TO_AIRP"},
        "query_jobs_enabled": True,
        "query_job_db_file": str(tmp_path / "query_jobs.sqlite3"),
        "query_job_result_directory": str(tmp_path / "results"),
        "query_job_max_rows": 10,
        "query_job_timeout_seconds": 30,
        "query_job_result_ttl_hours": 24,
        "query_job_poll_seconds": 1,
        "query_job_api_key": "job-api-secret",
    }
    values.update(overrides)
    return Settings(**values)


class FakeBackgroundRunner(SqlRunner):
    async def run_sql(
        self,
        args: RunSqlToolArgs,
        context: ToolContext,
    ) -> pd.DataFrame:
        assert context.metadata["background_query"] is True
        return pd.DataFrame(
            [
                {"FLIGHTNBR": "VN123", "FROM_AIRP": "VVNB"},
                {"FLIGHTNBR": "VN456", "FROM_AIRP": None},
            ]
        )


class FailingBackgroundRunner(SqlRunner):
    async def run_sql(
        self,
        args: RunSqlToolArgs,
        context: ToolContext,
    ) -> pd.DataFrame:
        raise RuntimeError("Oracle test failure")


def create_completed_job(
    tmp_path: Path,
) -> tuple[Settings, QueryJobStore, QueryJobService, dict[str, Any]]:
    settings = job_settings(tmp_path)
    store = QueryJobStore(settings.query_job_db_file)
    service = QueryJobService(
        settings=settings,
        store=store,
        sql_runner=FakeBackgroundRunner(),
    )
    job, created = service.enqueue(
        conversation_id="conversation-1",
        requested_by="tester@example.com",
        question="Danh sách chuyến bay",
        sql="SELECT FLIGHTNBR, FROM_AIRP FROM ATFM.T_DAY_FLIGHTS",
        idempotency_key="request-1",
    )
    assert created is True
    claimed = store.claim_next_job()
    assert claimed is not None
    service._execute_job(claimed)
    completed = store.get_job(str(job["id"]))
    assert completed is not None
    return settings, store, service, completed


def test_store_deduplicates_jobs_and_creates_completion_notification(tmp_path) -> None:
    settings, store, _, job = create_completed_job(tmp_path)

    duplicate, created = store.create_job(
        conversation_id="conversation-1",
        requested_by="tester@example.com",
        question="Duplicate",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
        idempotency_key="request-1",
    )

    assert created is False
    assert duplicate["id"] == job["id"]
    assert job["status"] == "succeeded"
    assert job["row_count"] == 2
    assert job["row_limit_reached"] is False
    assert (Path(settings.query_job_result_directory) / job["result_file"]).is_file()
    notifications = store.list_notifications(unread_only=True)
    assert notifications["unread_count"] == 1
    assert notifications["items"][0]["type"] == "query.completed"
    notification_id = notifications["items"][0]["id"]
    assert store.mark_notification_read(notification_id) is True
    assert store.list_notifications(unread_only=True)["items"] == []


def test_store_cancels_queued_job_and_notifies(tmp_path) -> None:
    settings = job_settings(tmp_path)
    store = QueryJobStore(settings.query_job_db_file)
    job, _ = store.create_job(
        conversation_id="conversation-1",
        requested_by="tester@example.com",
        question="Cancel me",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
    )

    cancelled, accepted = store.request_cancel(str(job["id"]))

    assert accepted is True
    assert cancelled is not None and cancelled["status"] == "cancelled"
    assert store.claim_next_job() is None
    notification = store.list_notifications()["items"][0]
    assert notification["type"] == "query.cancelled"


def test_store_recovers_interrupted_job(tmp_path) -> None:
    settings = job_settings(tmp_path)
    store = QueryJobStore(settings.query_job_db_file)
    job, _ = store.create_job(
        conversation_id="conversation-1",
        requested_by="tester@example.com",
        question="Recover me",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
    )
    assert store.claim_next_job() is not None

    assert store.requeue_interrupted_jobs() == 1
    recovered = store.get_job(str(job["id"]))
    assert recovered is not None and recovered["status"] == "queued"


def test_worker_thread_processes_queued_job(tmp_path) -> None:
    settings = job_settings(tmp_path)
    store = QueryJobStore(settings.query_job_db_file)
    service = QueryJobService(
        settings=settings,
        store=store,
        sql_runner=FakeBackgroundRunner(),
    )
    job, _ = service.enqueue(
        conversation_id="conversation-1",
        requested_by="tester@example.com",
        question="Run from worker",
        sql="SELECT FLIGHTNBR, FROM_AIRP FROM ATFM.T_DAY_FLIGHTS",
    )

    service.start()
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = store.get_job(str(job["id"]))
            if current is not None and current["status"] == "succeeded":
                break
            time.sleep(0.02)
        else:
            pytest.fail("background worker did not complete the queued job")
    finally:
        service.stop()

    assert store.list_notifications()["items"][0]["type"] == "query.completed"


def test_worker_failure_is_persisted_and_notified(tmp_path) -> None:
    settings = job_settings(tmp_path)
    store = QueryJobStore(settings.query_job_db_file)
    service = QueryJobService(
        settings=settings,
        store=store,
        sql_runner=FailingBackgroundRunner(),
    )
    job, _ = service.enqueue(
        conversation_id="conversation-1",
        requested_by="tester@example.com",
        question="Fail in background",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
    )
    claimed = store.claim_next_job()
    assert claimed is not None

    service._execute_job(claimed)

    failed = store.get_job(str(job["id"]))
    assert failed is not None and failed["status"] == "failed"
    assert "Oracle test failure" in failed["error"]
    notification = store.list_notifications()["items"][0]
    assert notification["type"] == "query.failed"


@pytest.mark.asyncio
async def test_background_tool_validates_sql_and_returns_job_card(tmp_path) -> None:
    settings = job_settings(tmp_path)
    store = QueryJobStore(settings.query_job_db_file)
    service = QueryJobService(
        settings=settings,
        store=store,
        sql_runner=FakeBackgroundRunner(),
    )
    tool = QueueBackgroundSqlTool(service)
    context = ToolContext.model_construct(
        user=User(id="tester@example.com", group_memberships=["user"]),
        conversation_id="conversation-1",
        request_id="request-1",
        agent_memory=None,
        metadata={},
    )

    result = await tool.execute(
        context,
        QueueBackgroundSqlArgs(
            question="Cho tôi danh sách chuyến bay",
            sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
        ),
    )

    assert result.success is True
    assert result.metadata["job_status"] == "queued"
    assert result.ui_component is not None
    assert "Mã công việc" in result.ui_component.rich_component.content
    with pytest.raises(QueryPolicyError):
        await tool.execute(
            context,
            QueueBackgroundSqlArgs(
                question="Xóa dữ liệu",
                sql="DELETE FROM ATFM.T_DAY_FLIGHTS",
            ),
        )


def test_integration_api_requires_key_and_returns_result_and_notifications(tmp_path) -> None:
    settings, store, _, job = create_completed_job(tmp_path)
    app = FastAPI()
    app.include_router(create_query_job_router(settings=settings, store=store))
    client = TestClient(app)
    headers = {"X-API-Key": settings.query_job_api_key}

    assert client.get("/api/integration/query-jobs").status_code == 401
    listing = client.get("/api/integration/query-jobs", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["result_available"] is True
    assert "result_file" not in listing.json()["items"][0]

    result = client.get(
        f"/api/integration/query-jobs/{job['id']}/result",
        headers=headers,
    )
    assert result.status_code == 200
    assert result.json()["row_count"] == 2
    assert result.json()["rows"][1]["FROM_AIRP"] is None

    notifications = client.get(
        "/api/integration/notifications?unread=true",
        headers=headers,
    )
    assert notifications.status_code == 200
    notification_id = notifications.json()["items"][0]["id"]
    marked = client.post(
        f"/api/integration/notifications/{notification_id}/read",
        headers=headers,
    )
    assert marked.status_code == 200
    assert marked.json() == {"ok": True}


def test_public_job_status_returns_only_done_without_api_key(tmp_path) -> None:
    settings, store, _, completed_job = create_completed_job(tmp_path)
    queued_job, _ = store.create_job(
        conversation_id="conversation-2",
        requested_by="guest@example.com",
        question="Queued query",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
    )
    app = FastAPI()
    app.include_router(create_query_job_router(settings=settings, store=store))
    client = TestClient(app)

    completed = client.get(
        f"/api/integration/query-jobs/{completed_job['id']}/status"
    )
    queued = client.get(f"/api/integration/query-jobs/{queued_job['id']}/status")

    assert completed.status_code == 200
    assert completed.json() == {"status": "done"}
    assert queued.status_code == 200
    assert queued.json() == {"status": "not_done"}
    assert set(completed.json()) == {"status"}
    assert client.get(
        "/api/integration/query-jobs/missing-job/status"
    ).status_code == 404


def test_expired_result_returns_gone(tmp_path) -> None:
    settings, store, _, job = create_completed_job(tmp_path)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with store._connect() as connection:
        connection.execute(
            "UPDATE query_jobs SET result_expires_at = ? WHERE id = ?",
            (expired, job["id"]),
        )
    app = FastAPI()
    app.include_router(create_query_job_router(settings=settings, store=store))

    response = TestClient(app).get(
        f"/api/integration/query-jobs/{job['id']}/result",
        headers={"X-API-Key": settings.query_job_api_key},
    )

    assert response.status_code == 410


def test_api_rejects_cancel_after_completion(tmp_path) -> None:
    settings, store, _, job = create_completed_job(tmp_path)
    app = FastAPI()
    app.include_router(create_query_job_router(settings=settings, store=store))

    response = TestClient(app).post(
        f"/api/integration/query-jobs/{job['id']}/cancel",
        headers={"X-API-Key": settings.query_job_api_key},
    )

    assert response.status_code == 409


def test_integration_api_key_does_not_require_application_basic_auth(tmp_path) -> None:
    settings = job_settings(tmp_path)
    store = QueryJobStore(settings.query_job_db_file)
    job, _ = store.create_job(
        conversation_id="conversation-public-status",
        requested_by="guest@example.com",
        question="Queued query",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
    )
    app = FastAPI()
    app.include_router(create_query_job_router(settings=settings, store=store))
    app.add_middleware(
        BasicAuthMiddleware,
        username="web-user",
        password="web-password",
        exempt_path_prefixes=("/api/integration/",),
    )

    response = TestClient(app).get(
        "/api/integration/query-jobs",
        headers={"X-API-Key": settings.query_job_api_key},
    )
    public_status = TestClient(app).get(
        f"/api/integration/query-jobs/{job['id']}/status"
    )

    assert response.status_code == 200
    assert public_status.status_code == 200
    assert public_status.json() == {"status": "not_done"}
