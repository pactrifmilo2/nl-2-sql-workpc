"""Validation, preview, approval, and Chroma synchronization for training."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp
from vanna.capabilities.sql_runner import RunSqlToolArgs, SqlRunner
from vanna.core.tool import ToolContext
from vanna.core.user.models import User

from .memory import ResilientChromaAgentMemory
from .settings import Settings
from .training_store import TrainingStore


class TrainingValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedSql:
    sql: str
    tables: tuple[str, ...]
    columns: tuple[str, ...]


def validate_training_sql(sql: str, settings: Settings) -> ValidatedSql:
    candidate = sql.strip().rstrip(";").strip()
    if not candidate:
        raise TrainingValidationError("SQL is required")
    try:
        statements = sqlglot.parse(candidate, read="oracle")
    except sqlglot.errors.ParseError as exc:
        raise TrainingValidationError(f"Invalid Oracle SQL: {exc}") from exc
    if len(statements) != 1:
        raise TrainingValidationError("Exactly one SQL statement is allowed")

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise TrainingValidationError("Only read-only SELECT queries are allowed")

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
        raise TrainingValidationError("Only read-only SELECT queries are allowed")

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
        raise TrainingValidationError("Training SQL must reference an allowed table")
    outside_tables = tables - settings.allowed_tables if settings.allowed_tables else set()
    if outside_tables:
        raise TrainingValidationError(
            "SQL references disallowed table(s): " + ", ".join(sorted(outside_tables))
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
    outside_columns = (
        columns - settings.allowed_columns - aliases
        if settings.allowed_columns
        else set()
    )
    if outside_columns:
        raise TrainingValidationError(
            "SQL references disallowed column(s): "
            + ", ".join(sorted(outside_columns))
        )

    return ValidatedSql(
        sql=statement.sql(dialect="oracle"),
        tables=tuple(sorted(tables)),
        columns=tuple(sorted(columns)),
    )


class TrainingService:
    def __init__(
        self,
        *,
        settings: Settings,
        store: TrainingStore,
        memory: ResilientChromaAgentMemory,
        sql_runner: SqlRunner,
    ) -> None:
        self.settings = settings
        self.store = store
        self.memory = memory
        self.sql_runner = sql_runner

    def _context(self, actor: str) -> ToolContext:
        request_id = str(uuid.uuid4())
        return ToolContext(
            user=User(
                id=actor,
                username=actor,
                group_memberships=["admin"],
            ),
            conversation_id=f"admin-training-{request_id}",
            request_id=request_id,
            agent_memory=self.memory,
        )

    async def preview(self, *, candidate_id: str, sql: str, actor: str) -> dict[str, Any]:
        if self.store.get_candidate(candidate_id) is None:
            raise KeyError(candidate_id)
        validated = validate_training_sql(sql, self.settings)
        preview_sql = (
            f"SELECT * FROM ({validated.sql}) "
            f"WHERE ROWNUM <= {self.settings.training_preview_row_limit}"
        )
        try:
            dataframe = await asyncio.wait_for(
                self.sql_runner.run_sql(
                    RunSqlToolArgs(sql=preview_sql), self._context(actor)
                ),
                timeout=self.settings.training_preview_timeout_seconds,
            )
        except Exception as exc:
            self.store.mark_test_result(
                candidate_id, success=False, error=str(exc)
            )
            raise TrainingValidationError(f"SQL preview failed: {exc}") from exc

        self.store.mark_test_result(candidate_id, success=True, error=None)
        rows = dataframe.head(self.settings.training_preview_row_limit).to_dict("records")
        return {
            "sql": validated.sql,
            "tables": list(validated.tables),
            "columns": list(dataframe.columns),
            "row_count": len(dataframe),
            "rows": rows,
        }

    async def approve(
        self,
        *,
        candidate_id: str,
        sql: str,
        actor: str,
        notes: str = "",
    ) -> dict[str, Any]:
        candidate = self.store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        if candidate["status"] == "rejected":
            raise TrainingValidationError("Rejected candidates cannot be approved")
        if candidate["status"] == "approved":
            raise TrainingValidationError("Candidate is already approved")

        validated = validate_training_sql(sql, self.settings)
        duplicate = self.store.find_active_duplicate(
            question=str(candidate["question"]),
            sql=validated.sql,
            exclude_candidate_id=candidate_id,
        )
        if duplicate is not None:
            raise TrainingValidationError(
                f"An identical active memory already exists: {duplicate['id']}"
            )

        preview = await self.preview(
            candidate_id=candidate_id, sql=validated.sql, actor=actor
        )
        memory_id = f"curated-{candidate_id}"
        metadata = {
            "source": "curated",
            "candidate_id": candidate_id,
            "approved_by": actor,
            "tables": list(validated.tables),
        }
        await self.memory.upsert_tool_memory(
            memory_id=memory_id,
            question=str(candidate["question"]),
            tool_name="run_sql",
            args={"sql": validated.sql},
            metadata=metadata,
        )
        self.store.approve_candidate(
            candidate_id=candidate_id,
            sql=validated.sql,
            memory_id=memory_id,
            actor=actor,
            notes=notes,
            metadata=metadata,
        )
        return {"candidate_id": candidate_id, "memory_id": memory_id, "preview": preview}

    async def disable_memory(self, *, memory_id: str, actor: str) -> bool:
        memory = self.store.get_memory(memory_id)
        if memory is None:
            raise KeyError(memory_id)
        deleted = await self.memory.delete_by_id(self._context(actor), memory_id)
        if not deleted and memory.get("status") == "active":
            raise TrainingValidationError("Memory was not found in Chroma")
        return self.store.disable_memory(memory_id, actor=actor)

    async def enable_memory(self, *, memory_id: str, actor: str) -> bool:
        memory = self.store.get_memory(memory_id)
        if memory is None:
            raise KeyError(memory_id)
        if memory.get("status") == "active":
            return True
        if memory.get("memory_type") == "tool":
            metadata = json.loads(memory.get("metadata_json") or "{}")
            await self.memory.upsert_tool_memory(
                memory_id=memory_id,
                question=str(memory.get("question") or ""),
                tool_name="run_sql",
                args={"sql": str(memory.get("sql") or "")},
                metadata=metadata,
            )
        else:
            await self.memory.upsert_text_memory(
                memory_id=memory_id,
                content=str(memory.get("content") or ""),
            )
        return self.store.enable_memory(memory_id, actor=actor)

    async def create_text_memory(self, *, content: str, actor: str) -> str:
        normalized = content.strip()
        if len(normalized) < 10:
            raise TrainingValidationError(
                "Domain memory must contain at least 10 characters"
            )
        memory_id = f"curated-text-{uuid.uuid4()}"
        await self.memory.upsert_text_memory(memory_id=memory_id, content=normalized)
        self.store.create_curated_text_memory(
            memory_id=memory_id, content=normalized, actor=actor
        )
        return memory_id
