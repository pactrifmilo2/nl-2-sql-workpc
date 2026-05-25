from vanna import Agent
from vanna.core.enhancer import DefaultLlmContextEnhancer
from .server import VannaFastAPIServerWithVoice

from .auth import create_user_resolver
from .database import create_db_tool
from .llm_context import CombinedEnhancer, TableScopeEnhancer
from .llm import create_llm_service
from .llm_middleware import TextToolCallMiddleware
from .memory import create_agent_memory
from .settings import settings
from .tools import create_tool_registry


def create_agent() -> Agent:
    llm = create_llm_service(settings)
    db_tool = create_db_tool(settings)
    agent_memory = create_agent_memory(settings)
    user_resolver = create_user_resolver()
    tools = create_tool_registry(db_tool)
    llm_context_enhancer = CombinedEnhancer(
        [
            DefaultLlmContextEnhancer(agent_memory),
            TableScopeEnhancer(settings.allowed_tables, settings.allowed_columns),
        ]
    )

    return Agent(
        llm_service=llm,
        tool_registry=tools,
        user_resolver=user_resolver,
        agent_memory=agent_memory,
        llm_context_enhancer=llm_context_enhancer,
        llm_middlewares=[TextToolCallMiddleware()],
    )


def create_server() -> VannaFastAPIServerWithVoice:
    agent = create_agent()
    return VannaFastAPIServerWithVoice(agent)
