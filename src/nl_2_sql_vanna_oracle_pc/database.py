import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext, ToolResult
from vanna.integrations.oracle import OracleRunner
from vanna.tools import RunSqlTool

from .settings import Settings

logger = logging.getLogger(__name__)


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
    async def execute(self, context: ToolContext, args: RunSqlToolArgs) -> ToolResult:
        logger.debug("run_sql invoked by user=%s", context.user.id)
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
            rich_component.max_rows_displayed = row_count

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
    oracle_runner = OracleRunner(
        user=settings.oracle_user,
        password=settings.oracle_password,
        dsn=settings.oracle_dsn,
    )

    return FullResultRunSqlTool(
        sql_runner=JsonSafeSqlRunner(oracle_runner)
    )
