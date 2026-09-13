from vanna.core.registry import ToolRegistry
from vanna.tools import RunSqlTool, VisualizeDataTool
from vanna.tools.agent_memory import (
    SearchSavedCorrectToolUsesTool,
)

from .clarification import AskClarificationTool
from .query_job_service import QueryJobService, QueueBackgroundSqlTool


def create_tool_registry(
    db_tool: RunSqlTool,
    query_job_service: QueryJobService | None = None,
) -> ToolRegistry:
    tools = ToolRegistry()

    tools.register_local_tool(db_tool, access_groups=["admin", "user"])
    tools.register_local_tool(AskClarificationTool(), access_groups=["admin", "user"])
    tools.register_local_tool(SearchSavedCorrectToolUsesTool(), access_groups=["admin", "user"])
    tools.register_local_tool(VisualizeDataTool(), access_groups=["admin", "user"])
    if query_job_service is not None:
        tools.register_local_tool(
            QueueBackgroundSqlTool(query_job_service),
            access_groups=["admin", "user"],
        )

    return tools

