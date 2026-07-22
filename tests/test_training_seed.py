import pytest

import nl_2_sql_vanna_oracle_pc.training as training
from nl_2_sql_vanna_oracle_pc.settings import Settings
from nl_2_sql_vanna_oracle_pc.training_store import TrainingStore


class SeedMemory:
    def __init__(self) -> None:
        self.tools = {}
        self.texts = {}
        self.clear_called = False
        self.duplicate_cleanup_calls = 0

    async def upsert_tool_memory(self, **values) -> None:
        self.tools[values["memory_id"]] = values

    async def upsert_text_memory(self, **values) -> None:
        self.texts[values["memory_id"]] = values

    async def remove_duplicate_tool_memories(self, **values) -> int:
        self.duplicate_cleanup_calls += 1
        return 0

    async def remove_duplicate_text_memories(self, **values) -> int:
        self.duplicate_cleanup_calls += 1
        return 0

    async def clear_memories(self, *args, **kwargs) -> int:
        self.clear_called = True
        raise AssertionError("Baseline synchronization must not clear memory")


@pytest.mark.asyncio
async def test_baseline_seed_is_idempotent_and_never_clears_curated_data(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        training,
        "settings",
        Settings(
            chroma_collection_name="test",
            allowed_tables={"T_DAY_FLIGHTS", "T_FINISHED_FLIGHTS"},
        ),
    )
    memory = SeedMemory()
    store = TrainingStore(tmp_path / "training.sqlite3")
    candidate_id = store.create_manual_candidate(
        question="curated question",
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
        actor="reviewer",
    )
    store.approve_candidate(
        candidate_id=candidate_id,
        sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
        memory_id="curated-one",
        actor="reviewer",
        notes="",
        metadata={},
    )

    await training.seed_agent_memory(memory, store)
    first_tool_ids = set(memory.tools)
    first_text_ids = set(memory.texts)
    await training.seed_agent_memory(memory, store)

    assert not memory.clear_called
    assert memory.duplicate_cleanup_calls > 0
    assert set(memory.tools) == first_tool_ids
    assert set(memory.texts) == first_text_ids
    assert store.get_memory("curated-one")["status"] == "active"
    assert "curated-one" in memory.tools
    assert all(
        memory_id.startswith("baseline-")
        for memory_id in first_tool_ids - {"curated-one"}
    )
