"""Audit logging for tool access, invocations, and results (Vanna 2)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from vanna.core.agent.config import AuditConfig, AgentConfig
from vanna.core.audit import AuditEvent, AuditLogger
from vanna.integrations.local import LoggingAuditLogger

from .settings import Settings

logger = logging.getLogger(__name__)


class FileAuditLogger(AuditLogger):
    """Append audit events as JSON lines to a file (Vanna docs pattern)."""

    def __init__(self, log_file_path: str | Path) -> None:
        self.log_file = Path(log_file_path)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    async def log_event(self, event: AuditEvent) -> None:
        try:
            event_dict = event.model_dump(mode="json", exclude_none=True)
            line = json.dumps(event_dict, separators=(",", ":")) + "\n"
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except Exception as exc:
            logger.error("Failed to write audit event: %s", exc, exc_info=True)


def create_audit_config(settings: Settings) -> AuditConfig:
    return AuditConfig(
        enabled=settings.audit_enabled,
        log_tool_access_checks=settings.audit_log_tool_access_checks,
        log_tool_invocations=settings.audit_log_tool_invocations,
        log_tool_results=settings.audit_log_tool_results,
        log_ui_feature_checks=settings.audit_log_ui_feature_checks,
        log_ai_responses=settings.audit_log_ai_responses,
        include_full_ai_responses=settings.audit_include_full_ai_responses,
        sanitize_tool_parameters=settings.audit_sanitize_tool_parameters,
    )


def create_agent_config(settings: Settings) -> AgentConfig:
    return AgentConfig(audit_config=create_audit_config(settings))


def create_audit_logger(settings: Settings) -> Optional[AuditLogger]:
    if not settings.audit_enabled:
        return None

    if settings.audit_log_file:
        return FileAuditLogger(settings.audit_log_file)

    return LoggingAuditLogger()
