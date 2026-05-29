"""Middleware for LLMs that emit tool calls as text instead of native tool_calls."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from vanna.core.llm import LlmRequest, LlmResponse, LlmService
from vanna.core.middleware import LlmMiddleware
from vanna.core.tool import ToolCall

from .tool_use import build_force_tool_request, should_force_tool_use

logger = logging.getLogger(__name__)

SQL_BLOCK_PATTERN = re.compile(r"```(?:sql)?\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
FENCED_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)


class ForceToolUseMiddleware(LlmMiddleware):
    """Retry once when a data question gets a conversational reply instead of run_sql."""

    def __init__(self, llm_service: LlmService):
        self.llm_service = llm_service
        self.text_tool_call_middleware = TextToolCallMiddleware()

    async def after_llm_response(
        self, request: LlmRequest, response: LlmResponse
    ) -> LlmResponse:
        response = await self.text_tool_call_middleware.after_llm_response(
            request, response
        )

        if not should_force_tool_use(request, response):
            return response

        logger.info("No tool call for data question; retrying with forced run_sql instruction")
        retry_request = build_force_tool_request(request)
        retry_response = await self.llm_service.send_request(retry_request)
        retry_response = await self.text_tool_call_middleware.after_llm_response(
            retry_request, retry_response
        )
        if retry_response.is_tool_call():
            logger.info("Force-tool retry produced tool call(s): %s", retry_response.tool_calls)
        else:
            logger.warning("Force-tool retry still returned no tool call")
        return retry_response


class TextToolCallMiddleware(LlmMiddleware):
    """Convert JSON-in-text or markdown SQL into structured tool_calls.

    Some Ollama models (e.g. qwen2.5-coder) return tool invocations in message
    content instead of the API tool_calls field, so Vanna never executes them.
    """

    async def after_llm_response(
        self, request: LlmRequest, response: LlmResponse
    ) -> LlmResponse:
        if response.is_tool_call() or not response.content:
            return response

        available_tools = {tool.name for tool in (request.tools or [])}
        if not available_tools:
            return response

        tool_calls = _parse_tool_calls_from_content(response.content, available_tools)
        if not tool_calls:
            return response

        logger.debug(
            "Parsed %d tool call(s) from text response: %s",
            len(tool_calls),
            [call.name for call in tool_calls],
        )
        remaining_content = _strip_parsed_content(response.content, tool_calls)
        return LlmResponse(
            content=remaining_content or None,
            tool_calls=tool_calls,
            finish_reason=response.finish_reason,
            usage=response.usage,
            metadata=response.metadata,
        )


def _parse_tool_calls_from_content(
    content: str, available_tools: set[str]
) -> list[ToolCall]:
    for parser in (_parse_json_tool_calls, _parse_sql_codeblock_tool_call):
        tool_calls = parser(content, available_tools)
        if tool_calls:
            return tool_calls
    return []


def _parse_json_tool_calls(content: str, available_tools: set[str]) -> list[ToolCall]:
    candidates = [content.strip()]
    candidates.extend(match.group(1).strip() for match in FENCED_BLOCK_PATTERN.finditer(content))
    candidates.extend(_extract_json_objects(content))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        tool_call = _tool_call_from_payload(payload, available_tools)
        if tool_call:
            return [tool_call]

    return []


def _extract_json_objects(text: str) -> list[str]:
    objects: list[str] = []
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if escape:
                escape = False
                continue
            if char == "\\" and in_string:
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    objects.append(text[start : index + 1])
                    start = text.find("{", index + 1)
                    break
        else:
            break
    return objects


def _tool_call_from_payload(
    payload: Any, available_tools: set[str]
) -> ToolCall | None:
    if isinstance(payload, list):
        for item in payload:
            tool_call = _tool_call_from_payload(item, available_tools)
            if tool_call:
                return tool_call
        return None

    if not isinstance(payload, dict):
        return None

    if "function" in payload and isinstance(payload["function"], dict):
        payload = payload["function"]

    name = payload.get("name")
    arguments = payload.get("arguments") or payload.get("args")
    if not name or name not in available_tools:
        return None

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {"sql": arguments}

    if not isinstance(arguments, dict):
        return None

    return ToolCall(
        id=f"parsed_{uuid.uuid4().hex[:8]}",
        name=name,
        arguments=arguments,
    )


def _parse_sql_codeblock_tool_call(
    content: str, available_tools: set[str]
) -> list[ToolCall]:
    if "run_sql" not in available_tools:
        return []

    match = SQL_BLOCK_PATTERN.search(content)
    if not match:
        return []

    sql = match.group(1).strip()
    if not sql:
        return []

    first_token = sql.split()[0].upper()
    if first_token not in {"SELECT", "WITH", "INSERT", "UPDATE", "DELETE"}:
        return []

    return [
        ToolCall(
            id=f"parsed_{uuid.uuid4().hex[:8]}",
            name="run_sql",
            arguments={"sql": sql},
        )
    ]


def _strip_parsed_content(content: str, tool_calls: list[ToolCall]) -> str | None:
    stripped = content.strip()

    try:
        json.loads(stripped)
        return None
    except json.JSONDecodeError:
        pass

    cleaned = FENCED_BLOCK_PATTERN.sub("", stripped)
    cleaned = SQL_BLOCK_PATTERN.sub("", cleaned).strip()
    if cleaned:
        return cleaned

    return None
