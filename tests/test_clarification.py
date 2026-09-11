import pytest
from pydantic import ValidationError
from vanna.core.llm import LlmMessage, LlmRequest, LlmResponse
from vanna.core.tool import ToolCall, ToolContext, ToolSchema
from vanna.core.user import User

from nl_2_sql_vanna_oracle_pc.clarification import (
    AskClarificationArgs,
    AskClarificationTool,
)
from nl_2_sql_vanna_oracle_pc.clarification_policy import (
    find_required_clarification,
)
from nl_2_sql_vanna_oracle_pc.content.vi import (
    CLARIFICATION_TOOL_RESULT,
    CLARIFICATION_WAIT_MESSAGE,
)
from nl_2_sql_vanna_oracle_pc.llm_middleware import (
    ForceToolUseMiddleware,
    _enforce_required_clarification,
    _prefer_clarification,
)
from nl_2_sql_vanna_oracle_pc.tool_use import build_force_tool_request
from nl_2_sql_vanna_oracle_pc.tools import create_tool_registry


def _tool_schema(name: str) -> ToolSchema:
    return ToolSchema(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
    )


def _request(messages: list[LlmMessage], *tool_names: str) -> LlmRequest:
    return LlmRequest(
        messages=messages,
        tools=[_tool_schema(name) for name in tool_names],
        user=User(id="test-user", group_memberships=["user"]),
        system_prompt="Base prompt",
    )


@pytest.mark.asyncio
async def test_clarification_tool_renders_question_and_choices() -> None:
    args = AskClarificationArgs(
        question="  Bạn muốn xem khoảng thời gian nào?  ",
        options=[
            {
                "label": "Hôm nay",
                "message": "Thống kê chuyến bay hôm nay",
            },
            {
                "label": "7 ngày gần nhất",
                "message": "Thống kê chuyến bay trong 7 ngày gần nhất",
            },
        ],
    )

    result = await AskClarificationTool().execute(None, args)  # type: ignore[arg-type]

    assert result.success is True
    assert result.metadata["awaiting_user_clarification"] is True
    assert result.ui_component is not None
    card = result.ui_component.rich_component
    assert card.content == "Bạn muốn xem khoảng thời gian nào?"
    assert [action["label"] for action in card.actions] == [
        "Hôm nay",
        "7 ngày gần nhất",
    ]
    assert card.actions[0]["action"] == "Thống kê chuyến bay hôm nay"


def test_clarification_tool_limits_options_to_three() -> None:
    with pytest.raises(ValidationError):
        AskClarificationArgs(
            question="Chọn một phương án",
            options=[
                {"label": str(index), "message": f"Lựa chọn {index}"}
                for index in range(4)
            ],
        )


@pytest.mark.asyncio
async def test_clarification_tool_is_registered_for_users() -> None:
    class FakeDbTool:
        name = "run_sql"

    registry = create_tool_registry(FakeDbTool())  # type: ignore[arg-type]

    assert "ask_clarification" in await registry.list_tools()

    context = ToolContext.model_construct(
        user=User(id="test-user", group_memberships=["user"]),
        conversation_id="conversation-1",
        request_id="request-1",
        agent_memory=None,
        metadata={},
    )
    result = await registry.execute(
        ToolCall(
            id="clarify-1",
            name="ask_clarification",
            arguments={
                "question": "Bạn muốn xem ngày nào?",
                "options": [
                    {
                        "label": "Hôm nay",
                        "message": "Xem chuyến bay hôm nay",
                    }
                ],
            },
        ),
        context,
    )
    assert result.success is True
    assert result.ui_component is not None


def test_clarification_wins_when_model_emits_sql_too() -> None:
    response = LlmResponse(
        content="I will do both",
        tool_calls=[
            ToolCall(
                id="sql-1",
                name="run_sql",
                arguments={"sql": "SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS"},
            ),
            ToolCall(
                id="clarify-1",
                name="ask_clarification",
                arguments={"question": "Bạn muốn xem ngày nào?"},
            ),
        ],
    )

    guarded = _prefer_clarification(response)

    assert guarded.content is None
    assert guarded.tool_calls is not None
    assert [call.name for call in guarded.tool_calls] == ["ask_clarification"]


def test_unresolved_flight_reference_requires_clarification() -> None:
    requirement = find_required_clarification(
        [LlmMessage(role="user", content="Cho tôi xem chuyến bay đó")]
    )

    assert requirement is not None
    assert requirement.kind == "flight_reference"
    assert requirement.options == ()


def test_multiple_flights_in_previous_result_remain_ambiguous() -> None:
    requirement = find_required_clarification(
        [
            LlmMessage(role="user", content="Cho tôi danh sách chuyến bay hôm nay"),
            LlmMessage(
                role="tool",
                content="FLIGHTNBR: VJC356, VJC1330, HVN1272",
                tool_call_id="sql-1",
            ),
            LlmMessage(role="user", content="Cho tôi xem chuyến bay đó"),
        ]
    )

    assert requirement is not None
    assert requirement.kind == "flight_reference"
    assert [option.label for option in requirement.options] == [
        "VJC356",
        "VJC1330",
        "HVN1272",
    ]


def test_single_flight_in_previous_turn_resolves_reference() -> None:
    requirement = find_required_clarification(
        [
            LlmMessage(role="user", content="Tìm chuyến bay VJC356"),
            LlmMessage(
                role="tool",
                content="FLIGHTNBR: VJC356",
                tool_call_id="sql-1",
            ),
            LlmMessage(role="user", content="Cho tôi xem chuyến bay đó"),
        ]
    )

    assert requirement is None


@pytest.mark.parametrize(
    ("question", "kind"),
    [
        ("Thống kê chuyến bay gần đây", "date_range"),
        ("Tìm chuyến bay gần nhất", "flight_status"),
        ("So sánh hai sân bay", "airport"),
        ("Cho tôi các chuyến bay trễ", "delay_metric"),
        ("Thống kê chuyến bay theo sân bay", "airport_role"),
        ("Vẽ biểu đồ số chuyến bay", "grouping"),
    ],
)
def test_common_ambiguities_have_deterministic_policies(
    question: str,
    kind: str,
) -> None:
    requirement = find_required_clarification(
        [LlmMessage(role="user", content=question)]
    )

    assert requirement is not None
    assert requirement.kind == kind


@pytest.mark.parametrize(
    "question",
    [
        "Cho tôi danh sách chuyến bay từ VVNB hôm nay",
        "Thống kê chuyến bay trong 7 ngày gần đây",
        "Vẽ biểu đồ số chuyến bay theo sân bay đi",
        "Cho tôi các chuyến bay trễ cất cánh",
        "Tìm chuyến bay VJC356",
        "Tìm vé chuyến bay",
    ],
)
def test_clear_questions_are_not_forced_to_clarify(question: str) -> None:
    requirement = find_required_clarification(
        [LlmMessage(role="user", content=question)]
    )

    assert requirement is None


def test_known_ambiguity_replaces_model_sql_call() -> None:
    request = _request(
        [LlmMessage(role="user", content="Cho tôi xem chuyến bay đó")],
        "run_sql",
        "ask_clarification",
    )
    attempted_sql = LlmResponse(
        tool_calls=[
            ToolCall(
                id="sql-1",
                name="run_sql",
                arguments={
                    "sql": "SELECT FLIGHTNBR FROM ATFM.T_FINISHED_FLIGHTS"
                },
            )
        ]
    )

    guarded = _enforce_required_clarification(request, attempted_sql)

    assert guarded.tool_calls is not None
    assert [call.name for call in guarded.tool_calls] == ["ask_clarification"]
    assert guarded.tool_calls[0].arguments["question"].startswith(
        "Bạn đang muốn xem chuyến bay nào?"
    )


@pytest.mark.asyncio
async def test_sql_is_blocked_until_user_answers_clarification() -> None:
    clarification_call = ToolCall(
        id="clarify-1",
        name="ask_clarification",
        arguments={"question": "Bạn muốn xem ngày nào?"},
    )
    request = _request(
        [
            LlmMessage(role="user", content="Thống kê chuyến bay gần đây"),
            LlmMessage(
                role="assistant",
                content="",
                tool_calls=[clarification_call],
            ),
            LlmMessage(
                role="tool",
                content=CLARIFICATION_TOOL_RESULT,
                tool_call_id="clarify-1",
            ),
        ],
        "run_sql",
        "ask_clarification",
    )
    attempted_sql = LlmResponse(
        tool_calls=[
            ToolCall(
                id="sql-1",
                name="run_sql",
                arguments={"sql": "SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS"},
            )
        ]
    )
    middleware = ForceToolUseMiddleware(object())  # type: ignore[arg-type]

    guarded = await middleware.after_llm_response(request, attempted_sql)

    assert guarded.tool_calls is None
    assert guarded.content == CLARIFICATION_WAIT_MESSAGE


def test_force_retry_allows_clarification_when_tool_is_available() -> None:
    request = _request(
        [LlmMessage(role="user", content="Thống kê chuyến bay gần đây")],
        "run_sql",
        "ask_clarification",
    )

    retry_request = build_force_tool_request(request)

    assert retry_request.system_prompt is not None
    assert "call\n   ask_clarification" in retry_request.system_prompt
    assert "Never call run_sql in the same response" in retry_request.system_prompt


def test_force_retry_remains_compatible_without_clarification_tool() -> None:
    request = _request(
        [LlmMessage(role="user", content="Cho tôi danh sách chuyến bay")],
        "run_sql",
    )

    retry_request = build_force_tool_request(request)

    assert retry_request.system_prompt is not None
    assert "You must call run_sql now" in retry_request.system_prompt
    assert "ask_clarification" not in retry_request.system_prompt
