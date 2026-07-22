from fastapi import FastAPI
from fastapi.testclient import TestClient

from nl_2_sql_vanna_oracle_pc.server import ReportsCORSMiddleware


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
