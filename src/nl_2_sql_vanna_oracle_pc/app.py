from vanna import Agent
from vanna.core.enhancer import DefaultLlmContextEnhancer
from .server import VannaFastAPIServerWithVoice

from .auth import create_user_resolver
from .database import create_db_tool
from .llm_context import (
    CombinedEnhancer,
    TableScopeEnhancer,
    ToolMemoryContextEnhancer,
)
from .llm import create_llm_service
from .llm_middleware import ForceToolUseMiddleware
from .memory import create_agent_memory
from .settings import settings
from .system_prompt import AtfmSystemPromptBuilder
from .tools import create_tool_registry
from .workflow import create_workflow_handler


def create_agent() -> Agent:
    llm = create_llm_service(settings)
    db_tool = create_db_tool(settings)
    agent_memory = create_agent_memory(settings)
    user_resolver = create_user_resolver()
    tools = create_tool_registry(db_tool)
    llm_context_enhancer = CombinedEnhancer(
        [
            DefaultLlmContextEnhancer(agent_memory),
            ToolMemoryContextEnhancer(agent_memory),
            TableScopeEnhancer(settings.allowed_tables, settings.allowed_columns),
        ]
    )

    return Agent(
        llm_service=llm,
        tool_registry=tools,
        user_resolver=user_resolver,
        agent_memory=agent_memory,
        system_prompt_builder=AtfmSystemPromptBuilder(),
        llm_context_enhancer=llm_context_enhancer,
        llm_middlewares=[ForceToolUseMiddleware(llm)],
        workflow_handler=create_workflow_handler(),
    )


def create_server() -> VannaFastAPIServerWithVoice:
    agent = create_agent()
    return VannaFastAPIServerWithVoice(agent)
