import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nl_2_sql_vanna_oracle_pc.admin_api import create_admin_router
from nl_2_sql_vanna_oracle_pc.admin_auth import AdminAuth
from nl_2_sql_vanna_oracle_pc.settings import Settings
from nl_2_sql_vanna_oracle_pc.training_service import TrainingService
from nl_2_sql_vanna_oracle_pc.training_store import TrainingStore

from test_training_service import FakeMemory, FakeRunner, scoped_settings


def test_admin_api_requires_signed_session_and_csrf(tmp_path) -> None:
    report_file = tmp_path / "reports.jsonl"
    feedback_file = tmp_path / "feedback.jsonl"
    report_file.write_text(
        json.dumps(
            {
                "report_id": "report-1",
                "timestamp": "2026-07-22T08:00:00+00:00",
                "conversation_id": "conversation-1",
                "user_id": "user@example.com",
                "question": "Danh sách chuyến bay",
                "generated_sql": "SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
                "success": True,
                "duration_ms": 100,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    settings = scoped_settings(
        admin_auth_user="reviewer",
        admin_auth_password="strong-password",
        admin_session_secret="test-secret-that-is-long-and-random",
        admin_session_cookie_secure=False,
        ai_report_log_file=str(report_file),
        hitl_feedback_log_file=str(feedback_file),
    )
    store = TrainingStore(tmp_path / "training.sqlite3")
    auth = AdminAuth(settings, store)
    service = TrainingService(
        settings=settings,
        store=store,
        memory=FakeMemory(),
        sql_runner=FakeRunner(),
    )
    app = FastAPI()
    app.include_router(
        create_admin_router(
            settings=settings,
            admin_auth=auth,
            store=store,
            service=service,
        )
    )
    client = TestClient(app)

    assert client.get("/api/admin/training/candidates").status_code == 401
    assert client.post(
        "/api/admin/login",
        json={"username": "reviewer", "password": "wrong"},
    ).status_code == 401

    login = client.post(
        "/api/admin/login",
        json={"username": "reviewer", "password": "strong-password"},
    )
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    issued_cookie = client.cookies.get(auth.cookie_name)

    assert client.get("/api/admin/reports").status_code == 200
    candidates = client.get("/api/admin/training/candidates")
    assert candidates.status_code == 200
    assert candidates.json()["total"] == 1

    payload = {
        "question": "Manual question",
        "sql": "SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
    }
    missing_csrf = client.post("/api/admin/training/candidates", json=payload)
    assert missing_csrf.status_code == 403, missing_csrf.json()
    created = client.post(
        "/api/admin/training/candidates",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 200

    logout = client.post(
        "/api/admin/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert logout.status_code == 200
    client.cookies.set(auth.cookie_name, issued_cookie)
    assert client.get("/api/admin/training/candidates").status_code == 401
