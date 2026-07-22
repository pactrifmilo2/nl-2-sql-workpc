from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from vanna.capabilities.agent_memory.base import AgentMemory
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner

from nl_2_sql_vanna_oracle_pc.settings import Settings
from nl_2_sql_vanna_oracle_pc.training_service import (
    TrainingService,
    TrainingValidationError,
    validate_training_sql,
)
from nl_2_sql_vanna_oracle_pc.training_store import TrainingStore


class FakeMemory(AgentMemory):
    def __init__(self) -> None:
        self.tool_memories: dict[str, dict[str, Any]] = {}
        self.text_memories: dict[str, str] = {}

    async def upsert_tool_memory(self, **values) -> None:
        self.tool_memories[values["memory_id"]] = values

    async def upsert_text_memory(self, **values) -> None:
        self.text_memories[values["memory_id"]] = values["content"]

    async def save_tool_usage(self, *args, **kwargs) -> None: ...
    async def save_text_memory(self, *args, **kwargs): ...
    async def search_similar_usage(self, *args, **kwargs): return []
    async def search_text_memories(self, *args, **kwargs): return []
    async def get_recent_memories(self, *args, **kwargs): return []
    async def get_recent_text_memories(self, *args, **kwargs): return []

    async def delete_by_id(self, context, memory_id: str) -> bool:
        return self.tool_memories.pop(memory_id, None) is not None or self.text_memories.pop(memory_id, None) is not None

    async def delete_text_memory(self, context, memory_id: str) -> bool:
        return self.text_memories.pop(memory_id, None) is not None

    async def clear_memories(self, *args, **kwargs) -> int: return 0


class FakeRunner(SqlRunner):
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def run_sql(self, args: RunSqlToolArgs, context) -> pd.DataFrame:
        self.queries.append(args.sql)
        return pd.DataFrame([{"FLIGHTNBR": "VN123"}])


def scoped_settings(**overrides) -> Settings:
    values = {
        "allowed_tables": {"T_DAY_FLIGHTS", "T_FINISHED_FLIGHTS"},
        "allowed_columns": {"FLIGHTNBR", "FROM_AIRP", "TO_AIRP"},
        "training_preview_row_limit": 10,
        "training_preview_timeout_seconds": 2,
    }
    values.update(overrides)
    return Settings(**values)


def test_sql_validation_enforces_read_only_scope() -> None:
    settings = scoped_settings()
    valid = validate_training_sql(
        "SELECT FLIGHTNBR, COUNT(*) AS N FROM ATFM.T_DAY_FLIGHTS GROUP BY FLIGHTNBR ORDER BY N",
        settings,
    )
    assert valid.tables == ("T_DAY_FLIGHTS",)

    invalid_queries = [
        "DELETE FROM ATFM.T_DAY_FLIGHTS",
        "SELECT FLIGHTNBR FROM ATFM.SECRET_TABLE",
        "SELECT PASSWORD FROM ATFM.T_DAY_FLIGHTS",
        "SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS FOR UPDATE",
        "SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS; SELECT 1 FROM DUAL",
    ]
    for query in invalid_queries:
        with pytest.raises(TrainingValidationError):
            validate_training_sql(query, settings)


@pytest.mark.asyncio
async def test_approval_previews_then_syncs_canonical_memory(tmp_path) -> None:
    store = TrainingStore(tmp_path / "training.sqlite3")
    memory = FakeMemory()
    runner = FakeRunner()
    service = TrainingService(
        settings=scoped_settings(),
        store=store,
        memory=memory,
        sql_runner=runner,
    )
    candidate_id = store.create_manual_candidate(
        question="Danh sách chuyến bay",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
        actor="reviewer",
    )

    result = await service.approve(
        candidate_id=candidate_id,
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
        actor="reviewer",
        notes="Checked",
    )

    assert "ROWNUM <= 10" in runner.queries[0]
    assert result["memory_id"] in memory.tool_memories
    assert store.get_candidate(candidate_id)["status"] == "approved"

    assert await service.disable_memory(
        memory_id=result["memory_id"], actor="reviewer"
    )
    assert store.get_memory(result["memory_id"])["status"] == "disabled"

    assert await service.enable_memory(
        memory_id=result["memory_id"], actor="reviewer"
    )
    assert store.get_memory(result["memory_id"])["status"] == "active"
    assert result["memory_id"] in memory.tool_memories
