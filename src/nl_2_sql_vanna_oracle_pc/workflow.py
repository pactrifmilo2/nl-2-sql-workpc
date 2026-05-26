"""Project-owned workflow handler for chat starter UI and commands."""

from typing import TYPE_CHECKING, Any, Dict

from vanna.components import RichTextComponent, UiComponent
from vanna.core.workflow import DefaultWorkflowHandler, WorkflowResult

from .content.vi import (
    SETUP_REQUIRED_MESSAGE,
    WELCOME_MESSAGE,
    build_help_message,
)

if TYPE_CHECKING:
    from vanna.core.agent.agent import Agent
    from vanna.core.storage import Conversation
    from vanna.core.user.models import User


class AtfmWorkflowHandler(DefaultWorkflowHandler):
    """Vietnamese starter UI and command responses."""

    async def try_handle(
        self,
        agent: "Agent",
        user: "User",
        conversation: "Conversation",
        message: str,
    ) -> WorkflowResult:
        if message.strip().lower() in ["/help", "help", "/h"]:
            is_admin = "admin" in user.group_memberships

            return WorkflowResult(
                should_skip_llm=True,
                components=[
                    UiComponent(
                        rich_component=RichTextComponent(
                            content=build_help_message(is_admin=is_admin),
                            markdown=True,
                        ),
                        simple_component=None,
                    )
                ],
            )

        return await super().try_handle(agent, user, conversation, message)

    def _generate_user_starter_card(self, analysis: Dict[str, Any]) -> UiComponent:
        content = SETUP_REQUIRED_MESSAGE if not analysis["has_sql"] else WELCOME_MESSAGE

        return UiComponent(
            rich_component=RichTextComponent(content=content, markdown=True),
            simple_component=None,
        )


def create_workflow_handler() -> AtfmWorkflowHandler:
    return AtfmWorkflowHandler()
