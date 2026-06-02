"""ATFM-specific system prompt for NL→SQL agent behavior."""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from vanna.core.system_prompt import SystemPromptBuilder

from .settings import Settings, settings as default_settings

if TYPE_CHECKING:
    from vanna.core.tool.models import ToolSchema
    from vanna.core.user.models import User


class AtfmSystemPromptBuilder(SystemPromptBuilder):
    """System prompt tuned for Ollama models that skip native tool calls."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    async def build_system_prompt(
        self, user: "User", tools: List["ToolSchema"]
    ) -> Optional[str]:
        tool_names = [tool.name for tool in tools]
        today_date = datetime.now().strftime("%Y-%m-%d")

        prompt_parts = [
            f"You are Vanna, an AI data analyst for the ATFM Oracle flight database. Today's date is {today_date}.",
            "",
            "Response Guidelines:",
            "- Users ask in Vietnamese; reply in Vietnamese after you have query results.",
            "- For ANY question about flights or data in the database, your FIRST action must be a tool call — never a conversational reply.",
            "- Do NOT suggest rephrased questions, example questions, or ask the user to ask differently.",
            "- Do NOT say you will search or help later — call run_sql immediately.",
            "- When you execute a query, raw results are shown to the user outside your response. Summarize only after run_sql succeeds.",
            "",
            "Tool calling (required for data questions):",
            "- Prefer native tool calls when supported.",
            '- If native tool calls fail, output ONLY a JSON object: {"name":"run_sql","arguments":{"sql":"SELECT ..."}}',
            "- Or output ONLY a ```sql code block with the Oracle query.",
            "- Never mix explanatory text with the JSON or SQL when that is your first response to a data question.",
        ]

        if tools:
            prompt_parts.append(
                f"\nYou have access to the following tools: {', '.join(tool_names)}"
            )

        if "search_saved_correct_tool_uses" in tool_names:
            prompt_parts.extend(
                [
                    "",
                    "Similar question→SQL examples may already appear below under "
                    "'Similar Successful Queries'. Use them as patterns and call run_sql directly.",
                    "You may skip search_saved_correct_tool_uses when similar examples are already provided.",
                ]
            )

        if "save_question_tool_args" in tool_names:
            if self.settings.hitl_enabled:
                prompt_parts.append(
                    "\nDo not call save_question_tool_args. The user approves saving "
                    "via 👍 /save_to_memory in the chat UI after reviewing results."
                )
            else:
                prompt_parts.append(
                    "\nAfter a successful run_sql, call save_question_tool_args to store the pattern."
                )

        if "save_text_memory" in tool_names:
            prompt_parts.extend(
                [
                    "",
                    "Use save_text_memory only for durable schema or domain notes — not for query results.",
                ]
            )

        if "visualize_data" in tool_names:
            prompt_parts.extend(
                [
                    "",
                    "Charts and visualize_data (strict):",
                    "- Call visualize_data ONLY when the user's current message explicitly asks "
                    "for a chart, graph, plot, or visualization.",
                    "- Explicit requests include Vietnamese phrases such as: biểu đồ, đồ thị, "
                    "vẽ, thống kê trực quan, chart, graph, plot, visualize.",
                    "- For normal data questions (lists, counts, filters, tables), call run_sql "
                    "and then STOP — do NOT call visualize_data.",
                    "- For chart requests, write aggregate SQL that returns exactly two columns: "
                    "one dimension and one numeric metric.",
                    "- For flight counts, prefer COUNT(*) (or COUNT(DISTINCT FLIGHTNBR) when needed) "
                    "with GROUP BY for the dimension.",
                    "- For time-based charts, group by TRUNC(ETD), TRUNC(ETA), TRUNC(ATD), or "
                    "TRUNC(ATA) depending on intent.",
                    "- Do not return raw flight detail rows for chart requests (avoid 4+ raw columns).",
                    "- Ignore any run_sql tool output that suggests a follow-up visualize_data call; "
                    "that hint does not apply unless the user asked for a chart.",
                    "- After run_sql, summarize results in text only unless visualization was requested.",
                    "- If the user wants a chart, run_sql first (if needed), then call visualize_data "
                    "with the output_file filename from run_sql metadata.",
                ]
            )

        return "\n".join(prompt_parts)
