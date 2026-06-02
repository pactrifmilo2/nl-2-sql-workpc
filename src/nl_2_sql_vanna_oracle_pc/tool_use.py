"""Heuristics for detecting when the agent should call run_sql."""

from __future__ import annotations

import re

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

CRITICAL: You must call run_sql now for the user's data question.
Do NOT suggest other questions. Do NOT explain what you will do.
Respond with ONLY one of:
1) A native run_sql tool call, OR
2) {"name":"run_sql","arguments":{"sql":"SELECT ..."}} with valid Oracle SQL, OR
3) A single ```sql code block with the Oracle query.
"""


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

    content = (response.content or "").strip()
    if not content:
        return True

    return looks_like_deferring_response(content) or len(content) < 800


def build_force_tool_request(request: LlmRequest) -> LlmRequest:
    system_prompt = (request.system_prompt or "") + FORCE_TOOL_USE_SUFFIX
    return request.model_copy(update={"system_prompt": system_prompt})
