from nl_2_sql_vanna_oracle_pc.training_store import TrainingStore


def sample_report() -> dict:
    return {
        "report_id": "report-1",
        "timestamp": "2026-07-22T08:00:00+00:00",
        "conversation_id": "conversation-1",
        "user_id": "user@example.com",
        "question": "Có bao nhiêu chuyến bay?",
        "generated_sql": "SELECT COUNT(*) FROM ATFM.T_DAY_FLIGHTS",
        "answer": "42",
        "success": True,
    }


def test_report_feedback_and_review_lifecycle_is_persistent(tmp_path) -> None:
    database = tmp_path / "training.sqlite3"
    store = TrainingStore(database)
    candidate_id = store.ingest_report(sample_report())

    assert candidate_id is not None
    assert store.ingest_report(sample_report()) == candidate_id
    assert store.list_candidates()["total"] == 1

    store.record_feedback(
        conversation_id="conversation-1",
        question="Có bao nhiêu chuyến bay?",
        sql="SELECT COUNT(*) FROM ATFM.T_DAY_FLIGHTS",
        action="approve",
        user_id="user@example.com",
    )
    candidate = store.get_candidate(candidate_id)
    assert candidate["feedback"] == "approve"
    assert candidate["status"] == "pending"

    store.mark_test_result(candidate_id, success=True, error=None)
    store.approve_candidate(
        candidate_id=candidate_id,
        sql="SELECT COUNT(*) FROM ATFM.T_DAY_FLIGHTS",
        memory_id=f"curated-{candidate_id}",
        actor="reviewer",
        notes="Verified",
        metadata={"source": "curated"},
    )

    reopened = TrainingStore(database)
    approved = reopened.get_candidate(candidate_id)
    memories = reopened.list_memories(status="active")
    audit = reopened.list_audit()

    assert approved["status"] == "approved"
    assert approved["reviewed_by"] == "reviewer"
    assert memories["total"] == 1
    assert memories["items"][0]["source_type"] == "curated"
    assert any(item["action"] == "candidate_approved" for item in audit)


def test_baseline_upsert_does_not_remove_curated_memory(tmp_path) -> None:
    store = TrainingStore(tmp_path / "training.sqlite3")
    candidate_id = store.create_manual_candidate(
        question="question",
        sql="SELECT * FROM ATFM.T_DAY_FLIGHTS",
        actor="reviewer",
    )
    store.approve_candidate(
        candidate_id=candidate_id,
        sql="SELECT * FROM ATFM.T_DAY_FLIGHTS",
        memory_id="curated-one",
        actor="reviewer",
        notes="",
        metadata={},
    )

    store.upsert_baseline_tool_memory(
        memory_id="baseline-one",
        question="baseline question",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
    )
    store.upsert_baseline_tool_memory(
        memory_id="baseline-one",
        question="baseline question",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
    )

    memories = store.list_memories(status="active")
    assert memories["total"] == 2
    assert {item["source_type"] for item in memories["items"]} == {
        "baseline",
        "curated",
    }


def test_feedback_creates_candidate_when_reporting_is_disabled(tmp_path) -> None:
    store = TrainingStore(tmp_path / "training.sqlite3")

    store.record_feedback(
        conversation_id="conversation-without-report",
        question="Danh sách chuyến bay",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
        action="approve",
        user_id="user@example.com",
    )

    candidates = store.list_candidates()
    assert candidates["total"] == 1
    assert candidates["items"][0]["feedback"] == "approve"
