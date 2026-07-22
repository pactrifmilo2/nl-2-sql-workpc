"""Same-origin admin API for reports and reviewed training mutations."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field

from .admin_auth import AdminAuth, AdminSession
from .reports import MAX_REPORT_LIMIT, _read_jsonl, build_ai_report
from .settings import Settings
from .training_service import TrainingService, TrainingValidationError
from .training_store import TrainingStore


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1000)


class CandidateRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    sql: str = Field(min_length=6, max_length=50000)
    notes: str = Field(default="", max_length=4000)


class SqlReviewRequest(BaseModel):
    sql: str = Field(min_length=6, max_length=50000)
    notes: str = Field(default="", max_length=4000)


class ReviewNotesRequest(BaseModel):
    notes: str = Field(default="", max_length=4000)


class TextMemoryRequest(BaseModel):
    content: str = Field(min_length=10, max_length=20000)


def create_admin_router(
    *,
    settings: Settings,
    admin_auth: AdminAuth,
    store: TrainingStore,
    service: TrainingService,
) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    def session_from_request(request: Request) -> AdminSession:
        if not admin_auth.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin authentication is not configured",
            )
        session = admin_auth.verify_token(request.cookies.get(admin_auth.cookie_name))
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin authentication required",
            )
        return session

    def mutation_session(
        request: Request,
        x_csrf_token: str = Header(default=""),
    ) -> AdminSession:
        session = session_from_request(request)
        if not admin_auth.verify_csrf(session, x_csrf_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing or invalid CSRF token",
            )
        return session

    async def load_reports_and_candidates() -> tuple[
        list[dict[str, Any]], list[dict[str, Any]]
    ]:
        records, feedback_records = await asyncio.gather(
            asyncio.to_thread(_read_jsonl, settings.ai_report_log_file),
            asyncio.to_thread(_read_jsonl, settings.hitl_feedback_log_file),
        )

        def ingest() -> None:
            for record in records:
                store.ingest_report(record)
            latest_feedback: dict[tuple[str, str], dict[str, Any]] = {}
            for feedback in feedback_records:
                conversation_id = str(feedback.get("conversation_id") or "")
                identity = str(
                    feedback.get("question") or feedback.get("sql") or ""
                )
                latest_feedback[(conversation_id, identity)] = feedback
            for feedback in latest_feedback.values():
                store.record_feedback(
                    conversation_id=str(feedback.get("conversation_id") or ""),
                    question=str(feedback.get("question") or ""),
                    sql=str(feedback.get("sql") or ""),
                    action=str(feedback.get("action") or ""),
                    user_id=str(feedback.get("user_id") or "unknown"),
                    record_audit=False,
                )

        await asyncio.to_thread(ingest)
        return records, feedback_records

    @router.post("/login")
    async def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
        if not admin_auth.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Configure ADMIN_AUTH_USER, ADMIN_AUTH_PASSWORD, and ADMIN_SESSION_SECRET",
            )
        if not admin_auth.authenticate(payload.username, payload.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid admin credentials",
            )
        token, session = admin_auth.issue_token(payload.username)
        response.set_cookie(
            key=admin_auth.cookie_name,
            value=token,
            max_age=settings.admin_session_ttl_hours * 3600,
            httponly=True,
            secure=settings.admin_session_cookie_secure,
            samesite="strict",
            path="/",
        )
        return {
            "authenticated": True,
            "username": session.username,
            "csrf_token": session.csrf_token,
            "expires_at": session.expires_at,
        }

    @router.get("/session")
    async def get_session(request: Request) -> dict[str, Any]:
        session = admin_auth.verify_token(request.cookies.get(admin_auth.cookie_name))
        if session is None:
            return {"configured": admin_auth.enabled, "authenticated": False}
        return {
            "configured": True,
            "authenticated": True,
            "username": session.username,
            "csrf_token": session.csrf_token,
            "expires_at": session.expires_at,
        }

    @router.post("/logout")
    async def logout(
        response: Response,
        session: AdminSession = Depends(mutation_session),
    ) -> dict[str, bool]:
        await asyncio.to_thread(admin_auth.revoke_session, session)
        response.delete_cookie(admin_auth.cookie_name, path="/")
        return {"ok": True}

    @router.get("/reports")
    async def reports(
        request: Request,
        start: datetime | None = None,
        end: datetime | None = None,
        success: bool | None = None,
        user_id: str | None = Query(default=None, max_length=320),
        limit: int = Query(default=50, ge=1, le=MAX_REPORT_LIMIT),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        session_from_request(request)
        if start is not None and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if start is not None and end is not None and start >= end:
            raise HTTPException(status_code=422, detail="start must be earlier than end")
        records, feedback_records = await load_reports_and_candidates()
        result = build_ai_report(
            records,
            feedback_records,
            start=start,
            end=end,
            success=success,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        states = await asyncio.to_thread(
            store.candidate_states_by_report,
            [str(item.get("report_id") or "") for item in result["items"]],
        )
        for item in result["items"]:
            state = states.get(str(item.get("report_id") or ""))
            item["training"] = state
        return result

    @router.get("/training/candidates")
    async def candidates(
        request: Request,
        candidate_status: str | None = Query(default=None, alias="status"),
        feedback: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        session_from_request(request)
        await load_reports_and_candidates()
        try:
            return await asyncio.to_thread(
                store.list_candidates,
                status=candidate_status,
                feedback=feedback,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/training/candidates/{candidate_id}")
    async def candidate(candidate_id: str, request: Request) -> dict[str, Any]:
        session_from_request(request)
        item = await asyncio.to_thread(store.get_candidate, candidate_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return item

    @router.post("/training/candidates")
    async def create_candidate(
        payload: CandidateRequest,
        session: AdminSession = Depends(mutation_session),
    ) -> dict[str, str]:
        candidate_id = await asyncio.to_thread(
            store.create_manual_candidate,
            question=payload.question,
            sql=payload.sql,
            actor=session.username,
            notes=payload.notes,
        )
        return {"id": candidate_id}

    @router.post("/training/candidates/{candidate_id}/preview")
    async def preview_candidate(
        candidate_id: str,
        payload: SqlReviewRequest,
        session: AdminSession = Depends(mutation_session),
    ) -> dict[str, Any]:
        try:
            return await service.preview(
                candidate_id=candidate_id,
                sql=payload.sql,
                actor=session.username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Candidate not found") from exc
        except TrainingValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/training/candidates/{candidate_id}/approve")
    async def approve_candidate(
        candidate_id: str,
        payload: SqlReviewRequest,
        session: AdminSession = Depends(mutation_session),
    ) -> dict[str, Any]:
        try:
            return await service.approve(
                candidate_id=candidate_id,
                sql=payload.sql,
                actor=session.username,
                notes=payload.notes,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Candidate not found") from exc
        except TrainingValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/training/candidates/{candidate_id}/reject")
    async def reject_candidate(
        candidate_id: str,
        payload: ReviewNotesRequest,
        session: AdminSession = Depends(mutation_session),
    ) -> dict[str, bool]:
        rejected = await asyncio.to_thread(
            store.reject_candidate,
            candidate_id,
            actor=session.username,
            notes=payload.notes,
        )
        if not rejected:
            raise HTTPException(
                status_code=409,
                detail="Candidate was not found or is already approved",
            )
        return {"ok": True}

    @router.get("/training/memories")
    async def memories(
        request: Request,
        memory_status: str | None = Query(default=None, alias="status"),
        limit: int = Query(default=200, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        session_from_request(request)
        try:
            return await asyncio.to_thread(
                store.list_memories,
                status=memory_status,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/training/memories/text")
    async def create_text_memory(
        payload: TextMemoryRequest,
        session: AdminSession = Depends(mutation_session),
    ) -> dict[str, str]:
        try:
            memory_id = await service.create_text_memory(
                content=payload.content, actor=session.username
            )
        except TrainingValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"id": memory_id}

    @router.post("/training/memories/{memory_id}/disable")
    async def disable_memory(
        memory_id: str,
        session: AdminSession = Depends(mutation_session),
    ) -> dict[str, bool]:
        try:
            disabled = await service.disable_memory(
                memory_id=memory_id, actor=session.username
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Memory not found") from exc
        except TrainingValidationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": disabled}

    @router.post("/training/memories/{memory_id}/enable")
    async def enable_memory(
        memory_id: str,
        session: AdminSession = Depends(mutation_session),
    ) -> dict[str, bool]:
        try:
            enabled = await service.enable_memory(
                memory_id=memory_id, actor=session.username
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Memory not found") from exc
        return {"ok": enabled}

    @router.get("/training/audit")
    async def audit(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        session_from_request(request)
        return {"items": await asyncio.to_thread(store.list_audit, limit)}

    return router
