import asyncio
import re
from uuid import uuid4

from vanna.capabilities.agent_memory.base import AgentMemory
from vanna.core.tool import ToolContext
from vanna.core.user.models import User

from .memory import create_agent_memory
from .settings import settings
from .training_data import BUSINESS_CONTEXT, TRAINING_EXAMPLES


TABLE_REFERENCE_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+([A-Z0-9_.$\"]+)", re.IGNORECASE)


def extract_referenced_tables(sql: str) -> set[str]:
    tables = set()

    for match in TABLE_REFERENCE_PATTERN.finditer(sql):
        table_name = match.group(1).strip('"').split(".")[-1].upper()
        tables.add(table_name)

    return tables


def uses_only_allowed_tables(sql: str, allowed_tables: set[str]) -> bool:
    if not allowed_tables:
        return True

    referenced_tables = extract_referenced_tables(sql)
    return referenced_tables <= allowed_tables


def create_training_user() -> User:
    return User(
        id="admin",
        email="admin@example.com",
        group_memberships=["admin"],
    )


def create_training_context(agent_memory: AgentMemory) -> ToolContext:
    return ToolContext(
        user=create_training_user(),
        conversation_id=f"training-{uuid4()}",
        request_id=f"training-{uuid4()}",
        agent_memory=agent_memory,
    )


async def seed_agent_memory(agent_memory: AgentMemory) -> None:
    context = create_training_context(agent_memory)

    for example in TRAINING_EXAMPLES:
        if not uses_only_allowed_tables(example.args["sql"], settings.allowed_tables):
            continue

        await agent_memory.save_tool_usage(
            question=example.question,
            tool_name=example.tool_name,
            args=example.args,
            context=context,
            success=True,
        )

    for context_text in BUSINESS_CONTEXT:
        await agent_memory.save_text_memory(
            content=context_text,
            context=context,
        )


async def main() -> None:
    agent_memory = create_agent_memory(settings)
    await seed_agent_memory(agent_memory)


if __name__ == "__main__":
    asyncio.run(main())
