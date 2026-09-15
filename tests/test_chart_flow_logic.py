import pytest

from nl_2_sql_vanna_oracle_pc.llm_middleware import _parse_json_tool_calls
from nl_2_sql_vanna_oracle_pc.system_prompt import AtfmSystemPromptBuilder
from nl_2_sql_vanna_oracle_pc.tool_use import (
    looks_like_chart_request,
    looks_like_data_question,
)


class _FakeTool:
    def __init__(self, name: str):
        self.name = name


class _FakeUser:
    id = "test-user"
    group_memberships = ["user"]


@pytest.mark.parametrize(
    "message",
    [
        "Vẽ biểu đồ số chuyến bay theo sân bay đi",
        "Tạo đồ thị số chuyến bay theo ngày",
        "Cho tôi chart delay hôm nay",
        "Thống kê trực quan theo sân bay đến",
    ],
)
def test_chart_keywords_are_detected(message: str) -> None:
    assert looks_like_chart_request(message) is True
    assert looks_like_data_question(message) is True


def test_non_chart_data_question_is_not_chart_request() -> None:
    message = "Cho tôi danh sách chuyến bay từ VVNB đến VVTS hôm nay"
    assert looks_like_data_question(message) is True
    assert looks_like_chart_request(message) is False


def test_visualize_data_json_tool_call_is_parsed() -> None:
    payload = (
        '{"name":"visualize_data","arguments":{"filename":"query_abcd.csv","title":"Demo"}}'
    )
    tool_calls = _parse_json_tool_calls(payload, {"run_sql", "visualize_data"})
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "visualize_data"
    assert tool_calls[0].arguments["filename"] == "query_abcd.csv"


def test_clarification_json_tool_call_is_parsed() -> None:
    payload = (
        '{"name":"ask_clarification","arguments":'
        '{"question":"Bạn muốn xem ngày nào?","options":'
        '[{"label":"Hôm nay","message":"Xem chuyến bay hôm nay"}]}}'
    )

    tool_calls = _parse_json_tool_calls(
        payload,
        {"run_sql", "ask_clarification"},
    )

    assert len(tool_calls) == 1
    assert tool_calls[0].name == "ask_clarification"
    assert tool_calls[0].arguments["options"][0]["label"] == "Hôm nay"


@pytest.mark.asyncio
async def test_system_prompt_includes_chart_rules_only_when_tool_present() -> None:
    builder = AtfmSystemPromptBuilder()
    user = _FakeUser()

    prompt_with_chart = await builder.build_system_prompt(
        user=user,
        tools=[_FakeTool("run_sql"), _FakeTool("visualize_data")],
    )
    assert prompt_with_chart is not None
    assert "Charts and visualize_data (strict):" in prompt_with_chart

    prompt_without_chart = await builder.build_system_prompt(
        user=user,
        tools=[_FakeTool("run_sql")],
    )
    assert prompt_without_chart is not None
    assert "Charts and visualize_data (strict):" not in prompt_without_chart


@pytest.mark.asyncio
async def test_system_prompt_includes_clarification_rules_only_when_tool_present() -> None:
    builder = AtfmSystemPromptBuilder()
    user = _FakeUser()

    prompt_with_clarification = await builder.build_system_prompt(
        user=user,
        tools=[_FakeTool("run_sql"), _FakeTool("ask_clarification")],
    )
    assert prompt_with_clarification is not None
    assert "Clarification (strict):" in prompt_with_clarification
    assert "Do not call run_sql in the same turn" in prompt_with_clarification

    prompt_without_clarification = await builder.build_system_prompt(
        user=user,
        tools=[_FakeTool("run_sql")],
    )
    assert prompt_without_clarification is not None
    assert "Clarification (strict):" not in prompt_without_clarification
    assert "ask_clarification" not in prompt_without_clarification


@pytest.mark.asyncio
async def test_system_prompt_describes_interactive_limits_without_background_jobs() -> None:
    builder = AtfmSystemPromptBuilder()

    prompt = await builder.build_system_prompt(
        user=_FakeUser(),
        tools=[_FakeTool("run_sql"), _FakeTool("ask_clarification")],
    )

    assert prompt is not None
    assert "Interactive query resource limits:" in prompt
    assert "background jobs are not available" in prompt
    assert "Before an unbounded historical detail query" in prompt


@pytest.mark.asyncio
async def test_system_prompt_defaults_data_questions_to_background_jobs() -> None:
    builder = AtfmSystemPromptBuilder()

    prompt = await builder.build_system_prompt(
        user=_FakeUser(),
        tools=[
            _FakeTool("run_sql"),
            _FakeTool("ask_clarification"),
            _FakeTool("queue_background_sql"),
        ],
    )

    assert prompt is not None
    assert "Background execution is available" in prompt
    assert "by default for every clear flight-data question" in prompt
    assert "Keep chart requests interactive" in prompt
    assert "background jobs are not available" not in prompt
