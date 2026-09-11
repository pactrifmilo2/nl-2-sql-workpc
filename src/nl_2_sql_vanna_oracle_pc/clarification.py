"""Tool for asking one focused clarification before generating SQL."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from vanna.components import CardComponent, SimpleTextComponent, UiComponent
from vanna.core.tool import Tool, ToolContext, ToolResult

from .content.vi import (
    CLARIFICATION_CARD_TITLE,
    CLARIFICATION_TOOL_RESULT,
)


class ClarificationOption(BaseModel):
    """A common interpretation the user can select in one click."""

    label: str = Field(
        min_length=1,
        max_length=80,
        description="Short Vietnamese label displayed on the button.",
    )
    message: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Self-contained Vietnamese request sent as the user's next message when "
            "the option is selected."
        ),
    )

    @field_validator("label", "message")
    @classmethod
    def strip_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class AskClarificationArgs(BaseModel):
    """Arguments for a single clarification question."""

    question: str = Field(
        min_length=1,
        max_length=500,
        description="One concise Vietnamese clarification question.",
    )
    options: list[ClarificationOption] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Up to three common choices. Leave empty when a free-form answer is needed."
        ),
    )

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class AskClarificationTool(Tool[AskClarificationArgs]):
    """Render a clarification question and optional one-click answers."""

    @property
    def name(self) -> str:
        return "ask_clarification"

    @property
    def description(self) -> str:
        return (
            "Ask exactly one concise Vietnamese clarification question before run_sql "
            "when missing or ambiguous information would materially change the table, "
            "filters, grouping, or meaning of the query. Provide two or three common "
            "options when useful. Do not use this tool for optional filters, safe "
            "defaults, or confirmation to run SQL."
        )

    def get_args_schema(self) -> type[AskClarificationArgs]:
        return AskClarificationArgs

    async def execute(
        self,
        context: ToolContext,
        args: AskClarificationArgs,
    ) -> ToolResult:
        actions = [
            {
                "label": option.label,
                "action": option.message,
                "variant": "secondary",
            }
            for option in args.options
        ]
        fallback_text = args.question
        if args.options:
            fallback_text += "\n" + "\n".join(
                f"- {option.label}" for option in args.options
            )

        return ToolResult(
            success=True,
            result_for_llm=CLARIFICATION_TOOL_RESULT,
            ui_component=UiComponent(
                rich_component=CardComponent(
                    title=CLARIFICATION_CARD_TITLE,
                    content=args.question,
                    icon="❓",
                    status="info",
                    actions=actions,
                    markdown=True,
                ),
                simple_component=SimpleTextComponent(text=fallback_text),
            ),
            metadata={"awaiting_user_clarification": True},
        )
