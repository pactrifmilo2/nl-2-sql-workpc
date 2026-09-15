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

from .clarification_policy import find_required_clarification
from .content.vi import CLARIFICATION_TOOL_RESULT, CLARIFICATION_WAIT_MESSAGE
from .tool_use import (
    build_force_tool_request,
    latest_user_message,
    should_route_to_background,
    should_force_tool_use,
)

logger = logging.getLogger(__name__)

SQL_BLOCK_PATTERN = re.compile(r"```(?:sql)?\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
FENCED_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)


class ForceToolUseMiddleware(LlmMiddleware):
    """Require a SQL or clarification action for flight-data questions."""

    def __init__(self, llm_service: LlmService):
        self.llm_service = llm_service
        self.text_tool_call_middleware = TextToolCallMiddleware()

    async def after_llm_response(
        self, request: LlmRequest, response: LlmResponse
    ) -> LlmResponse:
        response = await self.text_tool_call_middleware.after_llm_response(
            request, response
        )
        response = _prefer_clarification(response)
        response = _enforce_required_clarification(request, response)
        response = _enforce_background_default(request, response)

        if _follows_clarification_tool(request):
            if response.is_tool_call():
                logger.warning(
                    "Blocked tool call(s) after ask_clarification while awaiting user input"
                )
            return LlmResponse(
                content=CLARIFICATION_WAIT_MESSAGE,
                finish_reason=response.finish_reason,
                usage=response.usage,
                metadata=response.metadata,
            )

        if not should_force_tool_use(request, response):
            return response

        logger.info(
            "No action for data question; retrying with forced data-action instruction"
        )
        retry_request = build_force_tool_request(request)
        retry_response = await self.llm_service.send_request(retry_request)
        retry_response = await self.text_tool_call_middleware.after_llm_response(
            retry_request, retry_response
        )
        retry_response = _prefer_clarification(retry_response)
        retry_response = _enforce_required_clarification(
            retry_request,
            retry_response,
        )
        retry_response = _enforce_background_default(
            retry_request,
            retry_response,
        )
        if retry_response.is_tool_call():
            logger.info(
                "Force-action retry produced tool call(s): %s",
                retry_response.tool_calls,
            )
        else:
            logger.warning("Force-action retry still returned no tool call")
        return retry_response


def _enforce_background_default(
    request: LlmRequest,
    response: LlmResponse,
) -> LlmResponse:
    """Route clear data questions to the background SQL tool by default."""

    available_tools = {tool.name for tool in (request.tools or [])}
    if "queue_background_sql" not in available_tools:
        return response

    question = latest_user_message(request.messages)
    if not question or not should_route_to_background(question):
        return response

    tool_calls = response.tool_calls or []
    if any(call.name == "ask_clarification" for call in tool_calls):
        return response

    background_call = next(
        (call for call in tool_calls if call.name == "queue_background_sql"),
        None,
    )
    if background_call is not None:
        arguments = dict(background_call.arguments)
        arguments.setdefault("question", question)
        return response.model_copy(
            update={
                "content": None,
                "tool_calls": [
                    ToolCall(
                        id=background_call.id,
                        name="queue_background_sql",
                        arguments=arguments,
                    )
                ],
            }
        )

    sql_call = next(
        (call for call in tool_calls if call.name == "run_sql"),
        None,
    )
    if sql_call is None:
        return response

    sql = sql_call.arguments.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        return response

    logger.info("Routing data question to background query queue")
    return response.model_copy(
        update={
            "content": None,
            "tool_calls": [
                ToolCall(
                    id=f"background_{uuid.uuid4().hex[:8]}",
                    name="queue_background_sql",
                    arguments={"question": question, "sql": sql},
                )
            ],
        }
    )


def _prefer_clarification(response: LlmResponse) -> LlmResponse:
    """Never execute SQL alongside a clarification request."""

    tool_calls = response.tool_calls or []
    clarification_calls = [
        call for call in tool_calls if call.name == "ask_clarification"
    ]
    if not clarification_calls:
        return response

    if len(tool_calls) > 1:
        logger.warning(
            "Discarded %d tool call(s) emitted alongside ask_clarification",
            len(tool_calls) - 1,
        )
    return response.model_copy(
        update={"content": None, "tool_calls": [clarification_calls[0]]}
    )


def _enforce_required_clarification(
    request: LlmRequest,
    response: LlmResponse,
) -> LlmResponse:
    """Replace unsafe model guesses for known ambiguities with clarification."""

    available_tools = {tool.name for tool in (request.tools or [])}
    if "ask_clarification" not in available_tools:
        return response

    requirement = find_required_clarification(
        request.messages,
        background_enabled="queue_background_sql" in available_tools,
    )
    if requirement is None:
        return response

    if any(
        call.name == "ask_clarification"
        for call in (response.tool_calls or [])
    ):
        return response

    logger.info(
        "Enforcing clarification before tool execution: kind=%s",
        requirement.kind,
    )
    return response.model_copy(
        update={
            "content": None,
            "tool_calls": [
                ToolCall(
                    id=f"clarify_{uuid.uuid4().hex[:8]}",
                    name="ask_clarification",
                    arguments=requirement.to_tool_arguments(),
                )
            ],
        }
    )


def _follows_clarification_tool(request: LlmRequest) -> bool:
    """Return whether this LLM call immediately follows clarification UI output."""

    if len(request.messages) < 2 or request.messages[-1].role != "tool":
        return False

    if request.messages[-1].content != CLARIFICATION_TOOL_RESULT:
        return False

    assistant_message = request.messages[-2]
    if assistant_message.role != "assistant":
        return False

    return any(
        call.name == "ask_clarification"
        for call in (assistant_message.tool_calls or [])
    )


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
