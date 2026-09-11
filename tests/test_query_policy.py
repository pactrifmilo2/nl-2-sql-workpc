from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from vanna.capabilities.file_system import FileSystem
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user import User

from nl_2_sql_vanna_oracle_pc.database import (
    BoundedOracleRunner,
    FullResultRunSqlTool,
)
from nl_2_sql_vanna_oracle_pc.query_policy import (
    QueryPolicyError,
    apply_runtime_row_limit,
    validate_runtime_sql,
)
from nl_2_sql_vanna_oracle_pc.settings import Settings


def query_settings(**overrides: Any) -> Settings:
    values = {
        "oracle_user": "user",
        "oracle_password": "password",
        "oracle_dsn": "database",
        "allowed_tables": {"T_DAY_FLIGHTS", "T_FINISHED_FLIGHTS"},
        "allowed_columns": {
            "FLIGHTNBR",
            "FROM_AIRP",
            "TO_AIRP",
            "ETD",
            "ETA",
            "ATD",
            "ATA",
        },
        "query_max_rows": 5,
        "query_preview_rows": 3,
        "query_timeout_seconds": 2,
        "query_max_sql_chars": 2_000,
    }
    values.update(overrides)
    return Settings(**values)


def test_runtime_sql_validation_accepts_read_only_oracle_query() -> None:
    validated = validate_runtime_sql(
        """
        SELECT FROM_AIRP, COUNT(*) AS FLIGHT_COUNT
        FROM ATFM.T_DAY_FLIGHTS
        GROUP BY FROM_AIRP
        ORDER BY FLIGHT_COUNT DESC
        """,
        query_settings(),
    )

    assert validated.tables == ("T_DAY_FLIGHTS",)
    assert validated.columns == ("FLIGHT_COUNT", "FROM_AIRP")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM ATFM.T_DAY_FLIGHTS",
        "SELECT * FROM ATFM.T_DAY_FLIGHTS",
        "SELECT SECRET FROM ATFM.T_DAY_FLIGHTS",
        "SELECT FLIGHTNBR FROM ATFM.SECRET_TABLE",
        "SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS FOR UPDATE",
        "SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS; SELECT 1 FROM DUAL",
    ],
)
def test_runtime_sql_validation_rejects_unsafe_queries(sql: str) -> None:
    with pytest.raises(QueryPolicyError):
        validate_runtime_sql(sql, query_settings())


def test_runtime_sql_validation_rejects_excessive_sql_length() -> None:
    with pytest.raises(QueryPolicyError, match="quá dài"):
        validate_runtime_sql(
            "SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS",
            query_settings(query_max_sql_chars=20),
        )


def test_internal_training_preview_may_use_select_star_wrapper() -> None:
    validated = validate_runtime_sql(
        "SELECT * FROM (SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS) WHERE ROWNUM <= 10",
        query_settings(),
        allow_select_star=True,
    )

    assert validated.tables == ("T_DAY_FLIGHTS",)


def test_runtime_row_limit_wraps_query_after_inner_ordering() -> None:
    limited = apply_runtime_row_limit(
        "SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS ORDER BY ETD",
        500,
    )

    assert limited.startswith("SELECT * FROM (\n")
    assert "ORDER BY ETD\n) WHERE ROWNUM <= 500" in limited


class FakeCursor:
    description = [("FLIGHTNBR",)]

    def __init__(self) -> None:
        self.arraysize = 0
        self.executed_sql = ""
        self.fetch_size = 0
        self.closed = False

    def execute(self, sql: str) -> None:
        self.executed_sql = sql

    def fetchmany(self, size: int) -> list[tuple[str]]:
        self.fetch_size = size
        return [(f"VN{index}",) for index in range(size)]

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.call_timeout = 0
        self.cursor_instance = FakeCursor()
        self.closed = False
        self.rolled_back = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class FakeOracleModule:
    class Error(Exception):
        pass

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def connect(self, **kwargs: Any) -> FakeConnection:
        return self.connection


@pytest.mark.asyncio
async def test_bounded_oracle_runner_applies_limit_timeout_and_fetch_cap() -> None:
    settings = query_settings()
    connection = FakeConnection()
    runner = BoundedOracleRunner(settings=settings)
    runner.oracledb = FakeOracleModule(connection)
    context = ToolContext.model_construct(
        user=User(id="test-user", group_memberships=["user"]),
        conversation_id="conversation-1",
        request_id="request-1",
        agent_memory=None,
        metadata={},
    )

    dataframe = await runner.run_sql(
        RunSqlToolArgs(
            sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS ORDER BY ETD"
        ),
        context,
    )

    cursor = connection.cursor_instance
    assert len(dataframe) == settings.query_max_rows
    assert connection.call_timeout == 2_000
    assert cursor.fetch_size == settings.query_max_rows
    assert cursor.arraysize == settings.query_max_rows
    assert cursor.executed_sql.endswith("WHERE ROWNUM <= 5")
    assert cursor.closed is True
    assert connection.closed is True


class FakeRunner(SqlRunner):
    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        return pd.DataFrame(
            [{"FLIGHTNBR": f"VN{index}"} for index in range(5)]
        )


class FakeFileSystem(FileSystem):
    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    async def list_files(self, directory: str, context: ToolContext) -> list[str]:
        return list(self.files)

    async def read_file(self, filename: str, context: ToolContext) -> str:
        return self.files[filename]

    async def write_file(
        self,
        filename: str,
        content: str,
        context: ToolContext,
        overwrite: bool = False,
    ) -> None:
        self.files[filename] = content

    async def exists(self, path: str, context: ToolContext) -> bool:
        return path in self.files

    async def is_directory(self, path: str, context: ToolContext) -> bool:
        return False

    async def search_files(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def run_bash(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_sql_tool_limits_preview_and_reports_possible_truncation() -> None:
    tool = FullResultRunSqlTool(
        sql_runner=FakeRunner(),
        file_system=FakeFileSystem(),
        preview_row_limit=3,
        max_row_limit=5,
    )
    context = ToolContext.model_construct(
        user=User(id="test-user", group_memberships=["user"]),
        conversation_id="conversation-1",
        request_id="request-1",
        agent_memory=None,
        metadata={},
    )

    result = await tool.execute(
        context,
        RunSqlToolArgs(sql="SELECT FLIGHTNBR FROM ATFM.T_DAY_FLIGHTS"),
    )

    assert result.success is True
    assert result.metadata["row_limit_reached"] is True
    assert result.metadata["row_limit"] == 5
    assert result.ui_component is not None
    component = result.ui_component.rich_component
    assert component.max_rows_displayed == 3
    assert component.title == "Kết quả truy vấn"
    assert "có thể còn dữ liệu" in component.description
    assert "backend limited this result to 5 rows" in result.result_for_llm
