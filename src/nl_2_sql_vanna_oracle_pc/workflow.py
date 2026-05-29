"""Project-owned workflow handler for chat starter UI and commands."""

from typing import TYPE_CHECKING, Any, Dict, Optional

from vanna.components import RichTextComponent, UiComponent
from vanna.core.tool import ToolContext
from vanna.core.workflow import DefaultWorkflowHandler, WorkflowResult

from .content.vi import (
    HITL_CORRECT_DENIED,
    HITL_CORRECT_SUCCESS,
    HITL_CORRECT_USAGE,
    HITL_REJECT_ADMIN_HINT,
    HITL_REJECT_MESSAGE,
    HITL_SAVE_INVALID_SQL,
    HITL_SAVE_NO_PENDING,
    HITL_SAVE_SUCCESS_ADMIN,
    HITL_SAVE_SUCCESS_USER,
    SETUP_REQUIRED_MESSAGE,
    WELCOME_MESSAGE,
    build_help_message,
)
from .hitl import (
    PENDING_SAVE_KEY,
    FeedbackLogger,
    is_admin,
)
from .settings import Settings
from .sql_scope import uses_only_allowed_tables

if TYPE_CHECKING:
    from vanna.core.agent.agent import Agent
    from vanna.core.storage import Conversation
    from vanna.core.user.models import User


class AtfmWorkflowHandler(DefaultWorkflowHandler):
    """Vietnamese starter UI, HITL memory commands, and admin workflows."""

    def __init__(
        self,
        settings: Settings,
        feedback_logger: Optional[FeedbackLogger] = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.feedback_logger = feedback_logger

    async def try_handle(
        self,
        agent: "Agent",
        user: "User",
        conversation: "Conversation",
        message: str,
    ) -> WorkflowResult:
        normalized = message.strip()
        lower = normalized.lower()

        if lower in ["/help", "help", "/h"]:
            return WorkflowResult(
                should_skip_llm=True,
                components=[
                    UiComponent(
                        rich_component=RichTextComponent(
                            content=build_help_message(
                                is_admin=is_admin(user)
                            ),
                            markdown=True,
                        ),
                        simple_component=None,
                    )
                ],
            )

        if self.settings.hitl_enabled:
            if lower in ["/save_to_memory", "save_to_memory"]:
                return await self._handle_save_to_memory(agent, user, conversation)

            if lower in ["/reject_memory", "reject_memory"]:
                return await self._handle_reject_memory(agent, user, conversation)

            if lower.startswith("/correct_sql"):
                return await self._handle_correct_sql(
                    agent, user, conversation, normalized
                )

        return await super().try_handle(agent, user, conversation, message)

    async def _handle_save_to_memory(
        self,
        agent: "Agent",
        user: "User",
        conversation: "Conversation",
    ) -> WorkflowResult:
        pending = conversation.metadata.get(PENDING_SAVE_KEY)
        if not pending:
            return self._text_response(HITL_SAVE_NO_PENDING)

        sql = pending.get("args", {}).get("sql", "")
        question = pending.get("question", "")
        user_is_admin = is_admin(user)
        committed = False
        content = HITL_SAVE_SUCCESS_USER

        if user_is_admin:
            if not uses_only_allowed_tables(sql, self.settings.allowed_tables):
                return self._text_response(HITL_SAVE_INVALID_SQL)

            context = ToolContext(
                user=user,
                conversation_id=conversation.id,
                request_id=conversation.id,
                agent_memory=agent.agent_memory,
            )
            await agent.agent_memory.save_tool_usage(
                question=question,
                tool_name=pending.get("tool_name", "run_sql"),
                args=pending.get("args", {}),
                context=context,
                success=True,
            )
            committed = True
            content = HITL_SAVE_SUCCESS_ADMIN

        self._log_feedback(
            user_id=user.id,
            conversation_id=conversation.id,
            question=question,
            sql=sql,
            action="approve",
            committed=committed,
        )
        conversation.metadata.pop(PENDING_SAVE_KEY, None)
        await agent.conversation_store.update_conversation(conversation)
        return self._text_response(content)

    async def _handle_reject_memory(
        self,
        agent: "Agent",
        user: "User",
        conversation: "Conversation",
    ) -> WorkflowResult:
        pending = conversation.metadata.pop(PENDING_SAVE_KEY, None)
        sql = pending.get("args", {}).get("sql", "") if pending else ""
        question = pending.get("question", "") if pending else ""

        self._log_feedback(
            user_id=user.id,
            conversation_id=conversation.id,
            question=question,
            sql=sql,
            action="reject",
            committed=False,
        )
        await agent.conversation_store.update_conversation(conversation)

        content = HITL_REJECT_MESSAGE
        if is_admin(user):
            content += HITL_REJECT_ADMIN_HINT

        return self._text_response(content)

    async def _handle_correct_sql(
        self,
        agent: "Agent",
        user: "User",
        conversation: "Conversation",
        message: str,
    ) -> WorkflowResult:
        if not is_admin(user):
            return self._text_response(HITL_CORRECT_DENIED)

        sql = message[len("/correct_sql") :].strip()
        if not sql:
            return self._text_response(HITL_CORRECT_USAGE)

        if not uses_only_allowed_tables(sql, self.settings.allowed_tables):
            return self._text_response(HITL_SAVE_INVALID_SQL)

        pending = conversation.metadata.get(PENDING_SAVE_KEY)
        question = ""
        if pending:
            question = pending.get("question", "")
        if not question:
            for msg in reversed(conversation.messages):
                if msg.role == "user" and not msg.content.strip().startswith("/"):
                    question = msg.content.strip()
                    break

        if not question:
            return self._text_response(HITL_SAVE_NO_PENDING)

        args = {"sql": sql}
        context = ToolContext(
            user=user,
            conversation_id=conversation.id,
            request_id=conversation.id,
            agent_memory=agent.agent_memory,
        )
        await agent.agent_memory.save_tool_usage(
            question=question,
            tool_name="run_sql",
            args=args,
            context=context,
            success=True,
        )

        self._log_feedback(
            user_id=user.id,
            conversation_id=conversation.id,
            question=question,
            sql=sql,
            action="correct",
            committed=True,
        )
        conversation.metadata.pop(PENDING_SAVE_KEY, None)
        await agent.conversation_store.update_conversation(conversation)
        return self._text_response(HITL_CORRECT_SUCCESS)

    def _log_feedback(
        self,
        *,
        user_id: str,
        conversation_id: str,
        question: str,
        sql: str,
        action: str,
        committed: bool,
    ) -> None:
        if self.feedback_logger is None:
            return
        self.feedback_logger.log(
            user_id=user_id,
            conversation_id=conversation_id,
            question=question,
            sql=sql,
            action=action,
            committed=committed,
        )

    def _text_response(self, content: str) -> WorkflowResult:
        return WorkflowResult(
            should_skip_llm=True,
            components=[
                UiComponent(
                    rich_component=RichTextComponent(content=content, markdown=True),
                    simple_component=None,
                )
            ],
        )

    def _generate_user_starter_card(self, analysis: Dict[str, Any]) -> UiComponent:
        content = SETUP_REQUIRED_MESSAGE if not analysis["has_sql"] else WELCOME_MESSAGE

        return UiComponent(
            rich_component=RichTextComponent(content=content, markdown=True),
            simple_component=None,
        )


def create_workflow_handler(
    settings: Settings,
    feedback_logger: Optional[FeedbackLogger] = None,
) -> AtfmWorkflowHandler:
    return AtfmWorkflowHandler(settings=settings, feedback_logger=feedback_logger)
