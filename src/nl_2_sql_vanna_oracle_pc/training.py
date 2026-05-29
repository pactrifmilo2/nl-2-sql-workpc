import asyncio
from uuid import uuid4

from vanna.capabilities.agent_memory.base import AgentMemory
from vanna.core.tool import ToolContext
from vanna.core.user.models import User

from .memory import create_agent_memory
from .settings import settings
from .sql_scope import uses_only_allowed_tables
from .training_data import BUSINESS_CONTEXT, TRAINING_EXAMPLES


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
