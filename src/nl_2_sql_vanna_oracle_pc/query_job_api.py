"""API consumed by an external admin backend for jobs and notifications."""

from __future__ import annotations

import asyncio
import gzip
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, status

from .query_job_store import JOB_STATUSES, QueryJobStore
from .settings import Settings


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    item = dict(job)
    result_file = item.pop("result_file", None)
    expires_at = item.get("result_expires_at")
    unexpired = True
    if expires_at:
        expiry = datetime.fromisoformat(str(expires_at))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        unexpired = expiry > datetime.now(timezone.utc)
    item["result_available"] = bool(
        result_file and item.get("status") == "succeeded" and unexpired
    )
    if item["result_available"]:
        item["result_url"] = f"/api/integration/query-jobs/{item['id']}/result"
    return item


def create_query_job_router(
    *,
    settings: Settings,
    store: QueryJobStore,
) -> APIRouter:
    router = APIRouter(prefix="/api/integration", tags=["query-jobs"])

    def require_api_key(x_api_key: str) -> None:
        if not settings.query_jobs_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Background query jobs are disabled",
            )
        if not settings.query_job_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Configure QUERY_JOB_API_KEY",
            )
        if not secrets.compare_digest(x_api_key, settings.query_job_api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid query job API key",
            )

    @router.get("/query-jobs")
    async def list_query_jobs(
        job_status: str | None = Query(default=None, alias="status"),
        requested_by: str | None = Query(default=None, max_length=320),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        x_api_key: str = Header(default="", include_in_schema=False),
    ) -> dict[str, Any]:
        require_api_key(x_api_key)
        if job_status is not None and job_status not in JOB_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid job status")
        result = await asyncio.to_thread(
            store.list_jobs,
            status=job_status,
            requested_by=requested_by,
            limit=limit,
            offset=offset,
        )
        result["items"] = [_public_job(item) for item in result["items"]]
        return result

    @router.get("/query-jobs/{job_id}")
    async def get_query_job(
        job_id: str,
        x_api_key: str = Header(default="", include_in_schema=False),
    ) -> dict[str, Any]:
        require_api_key(x_api_key)
        job = await asyncio.to_thread(store.get_job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Query job not found")
        return _public_job(job)

    @router.get("/query-jobs/{job_id}/status")
    async def get_public_query_job_status(job_id: str) -> dict[str, str]:
        """Expose only terminal/non-terminal state without requiring an API key."""

        job = await asyncio.to_thread(store.get_job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Query job not found")
        done = job["status"] in {"succeeded", "failed", "cancelled"}
        return {"status": "done" if done else "not_done"}

    @router.get("/query-jobs/{job_id}/result")
    async def get_query_job_result(
        job_id: str,
        x_api_key: str = Header(default="", include_in_schema=False),
    ) -> dict[str, Any]:
        require_api_key(x_api_key)
        job = await asyncio.to_thread(store.get_job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Query job not found")
        if job["status"] != "succeeded":
            raise HTTPException(status_code=409, detail="Query job is not complete")
        expires_at = job.get("result_expires_at")
        if expires_at:
            expiry = datetime.fromisoformat(str(expires_at))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                raise HTTPException(status_code=410, detail="Query result has expired")
        filename = job.get("result_file")
        if not filename:
            raise HTTPException(status_code=410, detail="Query result is unavailable")
        result_directory = Path(settings.query_job_result_directory).resolve()
        result_path = (result_directory / Path(str(filename)).name).resolve()
        if result_path.parent != result_directory or not result_path.is_file():
            raise HTTPException(status_code=410, detail="Query result is unavailable")

        def read_result() -> dict[str, Any]:
            with gzip.open(result_path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("Invalid query result payload")
            return payload

        try:
            return await asyncio.to_thread(read_result)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500,
                detail="Could not read query result",
            ) from exc

    @router.post("/query-jobs/{job_id}/cancel", status_code=202)
    async def cancel_query_job(
        job_id: str,
        x_api_key: str = Header(default="", include_in_schema=False),
    ) -> dict[str, Any]:
        require_api_key(x_api_key)
        job, accepted = await asyncio.to_thread(store.request_cancel, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Query job not found")
        if not accepted:
            raise HTTPException(
                status_code=409,
                detail=f"Query job cannot be cancelled from status {job['status']}",
            )
        return {"accepted": True, "job": _public_job(job)}

    @router.get("/notifications")
    async def list_notifications(
        after_id: int = Query(default=0, ge=0),
        unread: bool = False,
        recipient_id: str | None = Query(default=None, max_length=320),
        limit: int = Query(default=100, ge=1, le=500),
        x_api_key: str = Header(default="", include_in_schema=False),
    ) -> dict[str, Any]:
        require_api_key(x_api_key)
        return await asyncio.to_thread(
            store.list_notifications,
            after_id=after_id,
            unread_only=unread,
            recipient_id=recipient_id,
            limit=limit,
        )

    @router.post("/notifications/{notification_id}/read")
    async def mark_notification_read(
        notification_id: int,
        x_api_key: str = Header(default="", include_in_schema=False),
    ) -> dict[str, bool]:
        require_api_key(x_api_key)
        found = await asyncio.to_thread(
            store.mark_notification_read, notification_id
        )
        if not found:
            raise HTTPException(status_code=404, detail="Notification not found")
        return {"ok": True}

    return router
