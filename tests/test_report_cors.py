from fastapi import FastAPI
from fastapi.testclient import TestClient

from nl_2_sql_vanna_oracle_pc.server import (
    QueryJobCORSMiddleware,
    ReportsCORSMiddleware,
)


def test_report_cors_does_not_expose_other_app_routes() -> None:
    app = FastAPI()

    @app.get("/api/reports/example")
    async def report_route() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/private")
    async def private_route() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        ReportsCORSMiddleware,
        allow_origins=["https://reports.example.com"],
        allow_methods=["GET"],
        allow_headers=["X-API-Key"],
    )
    client = TestClient(app)
    headers = {"Origin": "https://reports.example.com"}

    report_response = client.get("/api/reports/example", headers=headers)
    private_response = client.get("/private", headers=headers)

    assert report_response.headers["access-control-allow-origin"] == headers["Origin"]
    assert "access-control-allow-origin" not in private_response.headers


def test_query_job_cors_is_limited_to_integration_routes() -> None:
    app = FastAPI()

    @app.get("/api/integration/notifications")
    async def notification_route() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/admin/session")
    async def admin_route() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        QueryJobCORSMiddleware,
        allow_origins=["https://admin.example.com"],
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key"],
    )
    client = TestClient(app)
    headers = {"Origin": "https://admin.example.com"}

    notification_response = client.get(
        "/api/integration/notifications", headers=headers
    )
    admin_response = client.get("/api/admin/session", headers=headers)

    assert notification_response.headers["access-control-allow-origin"] == headers[
        "Origin"
    ]
    assert "access-control-allow-origin" not in admin_response.headers
