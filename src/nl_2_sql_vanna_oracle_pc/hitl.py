"""Human-in-the-loop memory approval: feedback UI and pending-save workflow."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from vanna import Agent
from vanna.components import (
    ButtonGroupComponent,
    ComponentType,
    UiComponent,
)
from vanna.core.lifecycle import LifecycleHook
from vanna.core.storage import ConversationStore
from vanna.core.tool import ToolContext, ToolResult

from .content.vi import HITL_THUMBS_DOWN_LABEL, HITL_THUMBS_UP_LABEL
from .settings import Settings

if TYPE_CHECKING:
    from vanna.core.tool import Tool
    from vanna.core.storage import Conversation
    from vanna.core.user.models import User

logger = logging.getLogger(__name__)

PENDING_SAVE_KEY = "pending_save"
HITL_TOOL_ARGS_KEY = "hitl_tool_args"
HITL_TOOL_NAME_KEY = "hitl_tool_name"

_tool_context_var: ContextVar[Optional[ToolContext]] = ContextVar(
    "hitl_tool_context", default=None
)
_feedback_ui_var: ContextVar[Optional[UiComponent]] = ContextVar(
    "hitl_feedback_ui", default=None
)
# Fallback store: Agent saves a stale conversation object at end of turn and can
# overwrite metadata.pending_save written by the hook. Keyed by conversation+user.
_pending_saves: Dict[tuple[str, str], Dict[str, Any]] = {}


def _pending_key(conversation_id: str, user_id: str) -> tuple[str, str]:
    return (conversation_id, user_id)


def stash_pending_save(
    conversation_id: str, user_id: str, pending: Dict[str, Any]
) -> None:
    _pending_saves[_pending_key(conversation_id, user_id)] = pending


def get_pending_save(conversation_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    return _pending_saves.get(_pending_key(conversation_id, user_id))


def clear_pending_save(conversation_id: str, user_id: str) -> None:
    _pending_saves.pop(_pending_key(conversation_id, user_id), None)


def is_admin(user: "User") -> bool:
    return "admin" in user.group_memberships


def get_last_user_question(conversation: "Conversation") -> str:
    for message in reversed(conversation.messages):
        if message.role != "user":
            continue
        content = message.content.strip()
        if content.startswith("/"):
            continue
        return content
    return ""


def build_pending_save(
    *,
    question: str,
    tool_name: str,
    args: Dict[str, Any],
    user_id: str,
) -> Dict[str, Any]:
    return {
        "question": question,
        "tool_name": tool_name,
        "args": args,
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_feedback_button_group() -> UiComponent:
    # ButtonGroupComponent expects flat dicts (see Vanna docs), not ButtonComponent
    # instances — nested components render as "undefined" in vanna-components.js.
    return UiComponent(
        rich_component=ButtonGroupComponent(
            buttons=[
                {
                    "label": HITL_THUMBS_UP_LABEL,
                    "action": "/save_to_memory",
                    "variant": "primary",
                },
                {
                    "label": HITL_THUMBS_DOWN_LABEL,
                    "action": "/reject_memory",
                    "variant": "secondary",
                },
            ],
            orientation="horizontal",
        ),
        simple_component=None,
    )


class FeedbackLogger:
    """Append HITL feedback events as JSON lines."""

    def __init__(self, log_file_path: str | Path) -> None:
        self.log_file = Path(log_file_path)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        *,
        user_id: str,
        conversation_id: str,
        question: str,
        sql: str,
        action: str,
        committed: bool,
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "question": question,
            "sql": sql,
            "action": action,
            "committed": committed,
        }
        try:
            line = json.dumps(event, separators=(",", ":")) + "\n"
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except Exception as exc:
            logger.error("Failed to write feedback event: %s", exc, exc_info=True)


def create_feedback_logger(settings: Settings) -> Optional[FeedbackLogger]:
    if not settings.hitl_feedback_log_file:
        return None
    return FeedbackLogger(settings.hitl_feedback_log_file)


class HitlLifecycleHook(LifecycleHook):
    """After successful run_sql, stage pending_save and queue feedback UI."""

    def __init__(
        self,
        *,
        settings: Settings,
        conversation_store: ConversationStore,
    ) -> None:
        self.settings = settings
        self.conversation_store = conversation_store

    async def before_tool(self, tool: "Tool[Any]", context: ToolContext) -> None:
        _tool_context_var.set(context)

    async def after_tool(self, result: ToolResult) -> Optional[ToolResult]:
        if not self.settings.hitl_enabled or not result.success:
            return None

        context = _tool_context_var.get()
        if context is None:
            return None

        tool_name = context.metadata.get(HITL_TOOL_NAME_KEY)
        tool_args = context.metadata.get(HITL_TOOL_ARGS_KEY)
        if tool_name != "run_sql" or not tool_args:
            return None

        try:
            conversation = await self.conversation_store.get_conversation(
                context.conversation_id, context.user
            )
            if conversation is None:
                logger.warning(
                    "HITL: conversation %s not found", context.conversation_id
                )
                return None

            question = get_last_user_question(conversation)
            pending = build_pending_save(
                question=question,
                tool_name=tool_name,
                args=tool_args,
                user_id=context.user.id,
            )
            conversation.metadata[PENDING_SAVE_KEY] = pending
            await self.conversation_store.update_conversation(conversation)
            stash_pending_save(context.conversation_id, context.user.id, pending)

            _feedback_ui_var.set(build_feedback_button_group())
            logger.debug(
                "HITL pending_save staged for conversation=%s user=%s",
                context.conversation_id,
                context.user.id,
            )
        except Exception as exc:
            logger.error("HITL after_tool failed: %s", exc, exc_info=True)

        return None


class HitlAgent(Agent):
    """Yield feedback UI immediately after run_sql dataframe results."""

    async def _send_message(self, *args: Any, **kwargs: Any):
        async for item in super()._send_message(*args, **kwargs):
            yield item
            feedback_ui = _feedback_ui_var.get()
            if feedback_ui is None:
                continue

            rich = getattr(item, "rich_component", None)
            if rich is None or getattr(rich, "type", None) != ComponentType.DATAFRAME:
                continue

            _feedback_ui_var.set(None)
            yield feedback_ui


def create_hitl_hook(
    settings: Settings, conversation_store: ConversationStore
) -> Optional[HitlLifecycleHook]:
    if not settings.hitl_enabled:
        return None
    return HitlLifecycleHook(
        settings=settings, conversation_store=conversation_store
    )


def create_agent_class(settings: Settings):
    if settings.hitl_enabled:
        return HitlAgent
    return Agent
