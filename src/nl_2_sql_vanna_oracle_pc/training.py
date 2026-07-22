import asyncio
import hashlib
import logging
from uuid import uuid4

from vanna.core.tool import ToolContext
from vanna.core.user.models import User

from .memory import ResilientChromaAgentMemory, create_agent_memory
from .settings import settings
from .sql_scope import uses_only_allowed_tables
from .training_data import BUSINESS_CONTEXT, TRAINING_EXAMPLES
from .training_store import TrainingStore, create_training_store

logger = logging.getLogger(__name__)


def create_training_user() -> User:
    return User(
        id="admin",
        email="admin@example.com",
        group_memberships=["admin"],
    )


def create_training_context(agent_memory: ResilientChromaAgentMemory) -> ToolContext:
    return ToolContext(
        user=create_training_user(),
        conversation_id=f"training-{uuid4()}",
        request_id=f"training-{uuid4()}",
        agent_memory=agent_memory,
    )


def baseline_memory_id(kind: str, *values: str) -> str:
    digest = hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()[:32]
    return f"baseline-{kind}-{digest}"


async def seed_agent_memory(
    agent_memory: ResilientChromaAgentMemory,
    training_store: TrainingStore | None = None,
) -> None:
    """Idempotently upsert baseline data without deleting curated memories."""

    seeded_tools = 0
    for example in TRAINING_EXAMPLES:
        if not uses_only_allowed_tables(example.args["sql"], settings.allowed_tables):
            continue

        sql = example.args["sql"].strip()
        memory_id = baseline_memory_id("tool", example.question, sql)
        await agent_memory.upsert_tool_memory(
            memory_id=memory_id,
            question=example.question,
            tool_name=example.tool_name,
            args={"sql": sql},
            metadata={"source": "baseline"},
        )
        await agent_memory.remove_duplicate_tool_memories(
            keep_memory_id=memory_id,
            question=example.question,
            tool_name=example.tool_name,
            args={"sql": sql},
        )
        if training_store is not None:
            training_store.upsert_baseline_tool_memory(
                memory_id=memory_id,
                question=example.question,
                sql=sql,
            )
        seeded_tools += 1

    for context_text in BUSINESS_CONTEXT:
        memory_id = baseline_memory_id("text", context_text)
        await agent_memory.upsert_text_memory(
            memory_id=memory_id,
            content=context_text,
        )
        await agent_memory.remove_duplicate_text_memories(
            keep_memory_id=memory_id,
            content=context_text,
        )
        if training_store is not None:
            training_store.upsert_baseline_text_memory(
                memory_id=memory_id,
                content=context_text,
            )

    synchronized_curated = 0
    if training_store is not None:
        curated = training_store.list_memories(status="active", limit=100000)["items"]
        for item in curated:
            if item["source_type"] != "curated":
                continue
            if item["memory_type"] == "tool":
                await agent_memory.upsert_tool_memory(
                    memory_id=item["id"],
                    question=item["question"],
                    tool_name="run_sql",
                    args={"sql": item["sql"]},
                    metadata=item["metadata"],
                )
            else:
                await agent_memory.upsert_text_memory(
                    memory_id=item["id"],
                    content=item["content"],
                )
            synchronized_curated += 1

    logger.info(
        "Synchronized %d baseline tool example(s), %d baseline text memory(ies), "
        "and %d curated memory(ies) into %s",
        seeded_tools,
        len(BUSINESS_CONTEXT),
        synchronized_curated,
        settings.chroma_collection_name,
    )


async def main() -> None:
    agent_memory = create_agent_memory(settings)
    await seed_agent_memory(agent_memory, create_training_store(settings))


if __name__ == "__main__":
    asyncio.run(main())
