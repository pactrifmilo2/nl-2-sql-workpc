from vanna.core.enhancer import DefaultLlmContextEnhancer
from vanna.integrations.local import MemoryConversationStore

from .server import VannaFastAPIServerWithVoice

from .admin_auth import AdminAuth, create_admin_auth
from .audit import create_agent_config, create_audit_logger
from .auth import create_user_resolver
from .logging_config import log_startup_summary
from .database import create_db_tool
from .hitl import (
    create_agent_class,
    create_feedback_logger,
    create_hitl_hook,
)
from .llm_context import (
    CombinedEnhancer,
    TableScopeEnhancer,
    ToolMemoryContextEnhancer,
)
from .llm import create_llm_service
from .llm_middleware import ForceToolUseMiddleware
from .memory import ResilientChromaAgentMemory, create_agent_memory
from .reports import create_ai_report_logger
from .settings import settings
from .system_prompt import AtfmSystemPromptBuilder
from .tools import create_tool_registry
from .training_service import TrainingService
from .training_store import TrainingStore, create_training_store
from .workflow import create_workflow_handler


def create_agent(
    *,
    db_tool=None,
    agent_memory: ResilientChromaAgentMemory | None = None,
    admin_auth: AdminAuth | None = None,
    training_store: TrainingStore | None = None,
):
    log_startup_summary(settings)
    llm = create_llm_service(settings)
    db_tool = db_tool or create_db_tool(settings)
    agent_memory = agent_memory or create_agent_memory(settings)
    admin_auth = admin_auth or create_admin_auth(settings, training_store)
    user_resolver = create_user_resolver(admin_auth)
    tools = create_tool_registry(db_tool)
    conversation_store = MemoryConversationStore()
    feedback_logger = create_feedback_logger(settings, training_store)
    ai_report_logger = create_ai_report_logger(settings, training_store)

    llm_context_enhancer = CombinedEnhancer(
        [
            DefaultLlmContextEnhancer(agent_memory),
            ToolMemoryContextEnhancer(agent_memory),
            TableScopeEnhancer(settings.allowed_tables, settings.allowed_columns),
        ]
    )

    lifecycle_hooks = []
    hitl_hook = create_hitl_hook(settings, conversation_store)
    if hitl_hook is not None:
        lifecycle_hooks.append(hitl_hook)

    agent_cls = create_agent_class(settings)

    return agent_cls(
        llm_service=llm,
        tool_registry=tools,
        user_resolver=user_resolver,
        agent_memory=agent_memory,
        conversation_store=conversation_store,
        config=create_agent_config(settings),
        audit_logger=create_audit_logger(settings),
        system_prompt_builder=AtfmSystemPromptBuilder(settings),
        llm_context_enhancer=llm_context_enhancer,
        llm_middlewares=[ForceToolUseMiddleware(llm)],
        workflow_handler=create_workflow_handler(settings, feedback_logger),
        lifecycle_hooks=lifecycle_hooks,
        ai_report_logger=ai_report_logger,
        ai_report_settings=settings,
    )


def create_server() -> VannaFastAPIServerWithVoice:
    training_store = create_training_store(settings)
    if training_store is None:
        raise RuntimeError("TRAINING_DB_FILE must be configured")
    admin_auth = create_admin_auth(settings, training_store)
    db_tool = create_db_tool(settings)
    agent_memory = create_agent_memory(settings)
    agent = create_agent(
        db_tool=db_tool,
        agent_memory=agent_memory,
        admin_auth=admin_auth,
        training_store=training_store,
    )
    training_service = TrainingService(
        settings=settings,
        store=training_store,
        memory=agent_memory,
        sql_runner=db_tool.sql_runner,
    )
    return VannaFastAPIServerWithVoice(
        agent,
        admin_auth=admin_auth,
        training_store=training_store,
        training_service=training_service,
    )
