"""Runtime validation and resource limits for LLM-generated Oracle SQL."""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from .settings import Settings


class QueryPolicyError(ValueError):
    """Raised before Oracle execution when generated SQL violates policy."""


@dataclass(frozen=True)
class ValidatedRuntimeSql:
    sql: str
    tables: tuple[str, ...]
    columns: tuple[str, ...]


def validate_runtime_sql(
    sql: str,
    settings: Settings,
    *,
    allow_select_star: bool = False,
) -> ValidatedRuntimeSql:
    candidate = sql.strip().rstrip(";").strip()
    if not candidate:
        raise QueryPolicyError("Câu SQL không được để trống.")
    if len(candidate) > settings.query_max_sql_chars:
        raise QueryPolicyError(
            "Câu SQL quá dài. Hãy thu hẹp yêu cầu hoặc chia thành câu hỏi nhỏ hơn."
        )

    try:
        statements = sqlglot.parse(candidate, read="oracle")
    except sqlglot.errors.ParseError as exc:
        raise QueryPolicyError("Câu SQL Oracle không hợp lệ.") from exc
    if len(statements) != 1:
        raise QueryPolicyError("Mỗi lần chỉ được phép chạy một câu SQL.")

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise QueryPolicyError("Chỉ cho phép truy vấn SELECT chỉ đọc.")

    disallowed = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Create,
        exp.Drop,
        exp.Alter,
        exp.Merge,
        exp.Command,
        exp.Transaction,
        exp.Lock,
        exp.Into,
    )
    if any(isinstance(node, disallowed) for node in statement.walk()):
        raise QueryPolicyError("Chỉ cho phép truy vấn SELECT chỉ đọc.")

    for select in statement.find_all(exp.Select):
        if not allow_select_star and any(
            projection.is_star for projection in select.expressions
        ):
            raise QueryPolicyError(
                "Không cho phép SELECT *. Hãy chỉ chọn các cột cần thiết."
            )

    cte_names = {
        cte.alias_or_name.upper()
        for cte in statement.find_all(exp.CTE)
        if cte.alias_or_name
    }
    tables = {
        table.name.upper()
        for table in statement.find_all(exp.Table)
        if table.name and table.name.upper() not in cte_names
    }
    if not tables:
        raise QueryPolicyError("Truy vấn phải sử dụng bảng dữ liệu được cho phép.")

    outside_tables = (
        tables - settings.allowed_tables if settings.allowed_tables else set()
    )
    if outside_tables:
        raise QueryPolicyError(
            "Truy vấn sử dụng bảng ngoài phạm vi cho phép: "
            + ", ".join(sorted(outside_tables))
        )

    aliases = {
        alias.alias.upper()
        for alias in statement.find_all(exp.Alias)
        if alias.alias
    }
    columns = {
        column.name.upper()
        for column in statement.find_all(exp.Column)
        if column.name and column.name != "*"
    }
    permitted_columns = set(settings.allowed_columns)
    if allow_select_star:
        # Oracle pseudocolumn used only by the server-owned training preview
        # wrapper. User-generated queries do not receive this exception.
        permitted_columns.add("ROWNUM")
    outside_columns = (
        columns - permitted_columns - aliases
        if settings.allowed_columns
        else set()
    )
    if outside_columns:
        raise QueryPolicyError(
            "Truy vấn sử dụng cột ngoài phạm vi cho phép: "
            + ", ".join(sorted(outside_columns))
        )

    return ValidatedRuntimeSql(
        sql=statement.sql(dialect="oracle"),
        tables=tuple(sorted(tables)),
        columns=tuple(sorted(columns)),
    )


def apply_runtime_row_limit(sql: str, max_rows: int) -> str:
    """Apply a trusted outer Oracle row cap while preserving inner ordering."""

    return f"SELECT * FROM (\n{sql}\n) WHERE ROWNUM <= {int(max_rows)}"
