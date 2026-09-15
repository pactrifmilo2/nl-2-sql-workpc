"""Heuristics for detecting when the agent should call run_sql."""

from __future__ import annotations

import re
import unicodedata

from vanna.core.llm import LlmMessage, LlmRequest, LlmResponse

DATA_QUESTION_PATTERN = re.compile(
    r"(chuy[êe]n bay|li[ệe]t k[êe]|cho t[ôo]i|c[óo]\s.+\s+kh[ôo]ng|"
    r"bao nhi[êe]u|h[ôo]m qua|h[ôo]m nay|trong ng[àa]y|"
    r"[đd][ãa]\s+ho[àa]n th[àa]nh|t[ừu]\s.+\s+[đd][ếe]n|"
    r"[đd]i qua|bay qua|s[âa]n bay|flight|flights|"
    r"top\s+\d+|danh s[áa]ch|t[ìi]m|hi[êe]n th[ịi]|"
    r"bi[ểe]u [đd][ồo]|[đd][ồo] th[ịi]|chart|graph|plot|v[ẽe]|tr[ựu]c quan)",
    re.IGNORECASE,
)

CHART_REQUEST_PATTERN = re.compile(
    r"(bi[ểe]u [đd][ồo]|[đd][ồo] th[ịi]|chart|graph|plot|"
    r"v[ẽe]|th[ốo]ng k[êe]\s+tr[ựu]c quan|tr[ựu]c quan h[óo]a|visualize)",
    re.IGNORECASE,
)

META_QUESTION_PATTERN = re.compile(
    r"(list tools|what can you|b[ạa]n c[óo] th[ểe] l[àa]m g[ìi]|"
    r"c[óo]ng c[ụụ]|tools? available|help me understand what you)",
    re.IGNORECASE,
)

DEFERRING_RESPONSE_PATTERN = re.compile(
    r"(b[ạa]n c[óo] th[ểe] s[ửu] d[ụụ]ng c[âa]u h[ỏo]i|c[âa]u h[ỏo]i sau|"
    r"t[ôo]i s[ẽe] gi[úu]p|t[ôo]i s[ẽe] t[ìi]m|"
    r"you can use the following question|i will help you|"
    r"let me help you find|here is a question you can ask)",
    re.IGNORECASE,
)

FORCE_TOOL_USE_SUFFIX = """

CRITICAL: Resolve the user's data question now. Do NOT explain what you will do.
Respond with exactly one appropriate action:
1) If the request is sufficiently clear, call run_sql with valid Oracle SQL.
2) If missing or ambiguous information would materially change the query, call
   ask_clarification with one Vietnamese question and up to three common options.
3) If the request cannot be answered from the allowed schema, briefly explain the
   supported scope in Vietnamese without inventing data.
Never call run_sql in the same response as ask_clarification.
For tool calls, use a native call or output ONLY a JSON tool object.
"""

BACKGROUND_FORCE_TOOL_USE_SUFFIX = """

CRITICAL: Resolve the user's data question now. Do NOT explain what you will do.
Respond with exactly one appropriate action:
1) For a sufficiently clear flight-data request, call queue_background_sql with
   the complete Vietnamese question and valid Oracle SQL.
2) If missing or ambiguous information would materially change the query, call
   ask_clarification with one Vietnamese question and up to three common options.
3) For a chart request, call run_sql unless the user explicitly requests background
   execution. Background jobs do not render charts in the chat UI.
4) If the user explicitly declines background execution, call run_sql.
5) If the request cannot be answered from the allowed schema, briefly explain the
   supported scope in Vietnamese without inventing data.
Never combine run_sql, ask_clarification, or queue_background_sql in one response.
For tool calls, use a native call or output ONLY a JSON tool object.
"""

RUN_SQL_ONLY_SUFFIX = """

CRITICAL: You must call run_sql now for the user's data question.
Do NOT suggest other questions. Do NOT explain what you will do.
Respond with ONLY a native run_sql tool call, a JSON run_sql tool object, or a
single ```sql code block containing valid Oracle SQL.
"""


def _normalize_for_matching(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    without_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return without_marks.replace("đ", "d")


def looks_like_background_request(text: str) -> bool:
    """Return whether the user explicitly requested deferred execution."""

    normalized = _normalize_for_matching(text)
    if re.search(
        r"\b(?:khong|dung)(?:\s+can)?\s+(?:chay nen|background)\b",
        normalized,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:chay nen|background)\b|\bthong bao khi hoan thanh\b",
            normalized,
        )
    )


def should_route_to_background(text: str) -> bool:
    """Default clear data questions to background unless interaction is required."""

    if not looks_like_data_question(text):
        return False
    normalized = _normalize_for_matching(text)
    if re.search(
        r"\b(?:khong|dung)(?:\s+can)?\s+(?:chay nen|background)\b",
        normalized,
    ):
        return False
    return looks_like_background_request(text) or not looks_like_chart_request(text)


def latest_user_message(messages: list[LlmMessage]) -> str | None:
    for message in reversed(messages):
        if message.role == "user" and message.content:
            return message.content
    return None


def looks_like_data_question(text: str) -> bool:
    if META_QUESTION_PATTERN.search(text):
        return False
    return bool(DATA_QUESTION_PATTERN.search(text))


def looks_like_chart_request(text: str) -> bool:
    return bool(CHART_REQUEST_PATTERN.search(text))


def build_chart_title(question: str) -> str:
    normalized = " ".join(question.split())
    if not normalized:
        return "Biểu đồ dữ liệu chuyến bay"
    return normalized[:100]


def looks_like_deferring_response(text: str) -> bool:
    return bool(DEFERRING_RESPONSE_PATTERN.search(text))


def should_force_tool_use(request: LlmRequest, response: LlmResponse) -> bool:
    if response.is_tool_call():
        return False

    available_tools = {tool.name for tool in (request.tools or [])}
    if "run_sql" not in available_tools:
        return False

    if request.messages and request.messages[-1].role != "user":
        return False

    user_message = latest_user_message(request.messages)
    if not user_message or not looks_like_data_question(user_message):
        return False

    if (
        "queue_background_sql" in available_tools
        and should_route_to_background(user_message)
    ):
        return True

    content = (response.content or "").strip()
    if not content:
        return True

    return looks_like_deferring_response(content) or len(content) < 800


def build_force_tool_request(request: LlmRequest) -> LlmRequest:
    available_tools = {tool.name for tool in (request.tools or [])}
    if "ask_clarification" in available_tools:
        suffix = (
            BACKGROUND_FORCE_TOOL_USE_SUFFIX
            if "queue_background_sql" in available_tools
            else FORCE_TOOL_USE_SUFFIX
        )
    else:
        suffix = RUN_SQL_ONLY_SUFFIX
    system_prompt = (request.system_prompt or "") + suffix
    return request.model_copy(update={"system_prompt": system_prompt})
