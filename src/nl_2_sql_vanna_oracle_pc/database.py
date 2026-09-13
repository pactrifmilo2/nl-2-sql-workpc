import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext, ToolResult
from vanna.integrations.oracle import OracleRunner
from vanna.tools import RunSqlTool

from .content.vi import build_query_result_description
from .query_policy import apply_runtime_row_limit, validate_runtime_sql
from .settings import Settings

logger = logging.getLogger(__name__)


class BoundedOracleRunner(OracleRunner):
    """Oracle runner with runtime validation, row limits, and a call timeout."""

    def __init__(
        self,
        *,
        settings: Settings,
        max_rows: int | None = None,
        timeout_seconds: int | None = None,
    ):
        super().__init__(
            user=settings.oracle_user,
            password=settings.oracle_password,
            dsn=settings.oracle_dsn,
        )
        self.settings = settings
        self.max_rows = max_rows or settings.query_max_rows
        self.timeout_seconds = timeout_seconds or settings.query_timeout_seconds

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        allow_select_star = bool(
            context.metadata.get("trusted_training_preview")
        )
        validated = validate_runtime_sql(
            args.sql,
            self.settings,
            allow_select_star=allow_select_star,
        )
        bounded_sql = apply_runtime_row_limit(
            validated.sql,
            self.max_rows,
        )

        conn = self.oracledb.connect(
            user=self.user,
            password=self.password,
            dsn=self.dsn,
            **self.kwargs,
        )
        conn.call_timeout = self.timeout_seconds * 1000
        cursor = conn.cursor()
        cursor.arraysize = min(self.max_rows, 1000)

        try:
            cursor.execute(bounded_sql)
            results = cursor.fetchmany(size=self.max_rows)
            columns = [description[0] for description in cursor.description]
            return pd.DataFrame(results, columns=columns)
        except self.oracledb.Error:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()


class JsonSafeSqlRunner(SqlRunner):
    def __init__(self, wrapped_runner: SqlRunner):
        self.wrapped_runner = wrapped_runner

    async def run_sql(self, args: RunSqlToolArgs, context: ToolContext) -> pd.DataFrame:
        df = await self.wrapped_runner.run_sql(args, context)
        return df.map(self._to_json_safe_value)

    def _to_json_safe_value(self, value: Any) -> Any:
        if pd.isna(value):
            return None

        if isinstance(value, Decimal):
            return float(value)

        if isinstance(value, (datetime, date)):
            return value.isoformat()

        return value


class FullResultRunSqlTool(RunSqlTool):
    def __init__(
        self,
        *args,
        preview_row_limit: int,
        max_row_limit: int,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.preview_row_limit = min(preview_row_limit, max_row_limit)
        self.max_row_limit = max_row_limit

    async def execute(self, context: ToolContext, args: RunSqlToolArgs) -> ToolResult:
        logger.debug("run_sql invoked by user=%s", context.user.id)
        context.metadata["hitl_tool_name"] = self.name
        context.metadata["hitl_tool_args"] = {"sql": args.sql}
        try:
            result = await super().execute(context, args)
        except Exception:
            logger.exception("run_sql failed for user=%s", context.user.id)
            raise

        row_count = result.metadata.get("row_count")
        rich_component = (
            result.ui_component.rich_component
            if result.ui_component
            else None
        )

        if isinstance(row_count, int) and hasattr(rich_component, "max_rows_displayed"):
            rich_component.max_rows_displayed = min(
                row_count,
                self.preview_row_limit,
            )
            rich_component.title = "Kết quả truy vấn"
            rich_component.description = build_query_result_description(
                row_count=row_count,
                column_count=len(result.metadata.get("columns", [])),
                preview_rows=self.preview_row_limit,
                max_rows=self.max_row_limit,
            )

            if row_count >= self.max_row_limit:
                result.metadata["row_limit_reached"] = True
                result.metadata["row_limit"] = self.max_row_limit
                result.result_for_llm += (
                    f"\n\nThe backend limited this result to {self.max_row_limit} rows. "
                    "Tell the user the result may be incomplete and suggest narrowing "
                    "the date range, airport, or flight number."
                )

        if result.success:
            logger.debug("run_sql succeeded: rows=%s user=%s", row_count, context.user.id)
        else:
            logger.warning(
                "run_sql returned error for user=%s: %s",
                context.user.id,
                result.error,
            )

        return result


def create_db_tool(settings: Settings) -> RunSqlTool:
    oracle_runner = BoundedOracleRunner(settings=settings)

    return FullResultRunSqlTool(
        sql_runner=JsonSafeSqlRunner(oracle_runner),
        preview_row_limit=settings.query_preview_rows,
        max_row_limit=settings.query_max_rows,
    )


def create_background_sql_runner(settings: Settings) -> SqlRunner:
    """Create a safe runner with the larger, explicit background-job budget."""

    return JsonSafeSqlRunner(
        BoundedOracleRunner(
            settings=settings,
            max_rows=settings.query_job_max_rows,
            timeout_seconds=settings.query_job_timeout_seconds,
        )
    )
