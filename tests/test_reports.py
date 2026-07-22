import json
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nl_2_sql_vanna_oracle_pc.reports import (
    RequestTrace,
    ToolExecutionTrace,
    build_ai_report,
    build_request_report_event,
    create_reports_router,
)
from nl_2_sql_vanna_oracle_pc.settings import Settings


def test_request_report_contains_question_generation_and_timings() -> None:
    tool_call = SimpleNamespace(
        name="run_sql",
        arguments={"sql": "SELECT COUNT(*) FROM ATFM.T_DAY_FLIGHTS"},
    )
    conversation = SimpleNamespace(
        messages=[
            SimpleNamespace(role="user", content="Có bao nhiêu chuyến bay?"),
            SimpleNamespace(
                role="assistant", content="", tool_calls=[tool_call]
            ),
            SimpleNamespace(role="tool", content="42", tool_calls=None),
            SimpleNamespace(
                role="assistant", content="Có 42 chuyến bay.", tool_calls=None
            ),
        ]
    )
    trace = RequestTrace(
        request_id="request-1",
        tool_executions=[
            ToolExecutionTrace(
                name="run_sql",
                success=True,
                execution_time_ms=125.25,
                row_count=1,
            )
        ],
    )

    event = build_request_report_event(
        settings=Settings(ollama_model="qwen-test"),
        conversation=conversation,
        conversation_id="conversation-1",
        user_id="user@example.com",
        question="Có bao nhiêu chuyến bay?",
        started_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        duration_ms=500.5,
        trace=trace,
        processing_error=None,
    )

    assert event["question"] == "Có bao nhiêu chuyến bay?"
    assert event["generated_sql"] == "SELECT COUNT(*) FROM ATFM.T_DAY_FLIGHTS"
    assert event["answer"] == "Có 42 chuyến bay."
    assert event["model"] == "qwen-test"
    assert event["duration_ms"] == 500.5
    assert event["sql_execution_time_ms"] == 125.25
    assert event["rows_returned"] == 1
    assert event["success"] is True


def test_sensitive_tool_arguments_are_redacted() -> None:
    tool_call = SimpleNamespace(
        name="example",
        arguments={"api_token": "secret", "safe": "visible"},
    )
    conversation = SimpleNamespace(
        messages=[
            SimpleNamespace(role="user", content="question"),
            SimpleNamespace(role="assistant", content="answer", tool_calls=[tool_call]),
        ]
    )

    event = build_request_report_event(
        settings=Settings(),
        conversation=conversation,
        conversation_id="conversation-1",
        user_id="user@example.com",
        question="question",
        started_at=datetime.now(timezone.utc),
        duration_ms=1,
        trace=RequestTrace(),
        processing_error=None,
    )

    assert event["tool_calls"][0]["arguments"] == {
        "api_token": "[REDACTED]",
        "safe": "visible",
    }


def test_ai_report_builds_performance_and_feedback_summary() -> None:
    records = [
        {
            "report_id": "1",
            "timestamp": "2026-07-22T08:00:00+00:00",
            "conversation_id": "conversation-1",
            "user_id": "a@example.com",
            "generated_sql": "SELECT 1",
            "success": True,
            "duration_ms": 100,
            "sql_execution_time_ms": 20,
        },
        {
            "report_id": "2",
            "timestamp": "2026-07-22T09:00:00+00:00",
            "conversation_id": "conversation-2",
            "user_id": "b@example.com",
            "generated_sql": "SELECT 2",
            "success": False,
            "duration_ms": 300,
            "sql_execution_time_ms": 40,
        },
    ]
    feedback = [
        {
            "conversation_id": "conversation-1",
            "sql": "SELECT 1",
            "action": "approve",
        },
        {
            "conversation_id": "conversation-2",
            "question": "second question",
            "sql": "SELECT 2 CORRECTED",
            "action": "correct",
        },
    ]
    records[1]["question"] = "second question"

    report = build_ai_report(records, feedback)

    assert report["summary"]["total_requests"] == 2
    assert report["summary"]["success_rate_percent"] == 50.0
    assert report["summary"]["average_duration_ms"] == 200.0
    assert report["summary"]["average_sql_execution_ms"] == 30.0
    assert report["summary"]["approval_rate_percent"] == 50.0
    assert report["summary"]["corrected_requests"] == 1
    assert [item["report_id"] for item in report["items"]] == ["2", "1"]


def test_ai_report_endpoint_reads_jsonl_and_requires_api_key(tmp_path) -> None:
    report_file = tmp_path / "ai_report.jsonl"
    report_file.write_text(
        json.dumps(
            {
                "report_id": "report-1",
                "timestamp": "2026-07-22T08:00:00+00:00",
                "conversation_id": "conversation-1",
                "user_id": "user@example.com",
                "generated_sql": "SELECT 1",
                "success": True,
                "duration_ms": 100,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    settings = Settings(
        report_api_key="secret",
        ai_report_log_file=str(report_file),
        hitl_feedback_log_file=str(tmp_path / "feedback.jsonl"),
    )
    app = FastAPI()
    app.include_router(create_reports_router(settings))
    client = TestClient(app)

    assert client.get("/api/reports/ai").status_code == 401
    response = client.get(
        "/api/reports/ai", headers={"X-API-Key": "secret"}
    )

    assert response.status_code == 200
    assert response.json()["summary"]["total_requests"] == 1
    assert response.json()["items"][0]["report_id"] == "report-1"
    item_response = client.get(
        "/api/reports/ai/report-1", headers={"X-API-Key": "secret"}
    )
    assert item_response.status_code == 200


def test_ai_report_endpoint_is_not_public_without_authentication() -> None:
    app = FastAPI()
    app.include_router(create_reports_router(Settings(report_api_key="")))

    response = TestClient(app).get("/api/reports/ai")

    assert response.status_code == 503
