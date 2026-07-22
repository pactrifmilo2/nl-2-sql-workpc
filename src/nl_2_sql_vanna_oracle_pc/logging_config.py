"""Application debug logging (separate from audit trail)."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from .settings import Settings

APP_LOGGER_NAME = "nl_2_sql_vanna_oracle_pc"
_configured = False


def parse_log_level(name: str, default: int = logging.INFO) -> int:
    level = getattr(logging, name.strip().upper(), None)
    if isinstance(level, int):
        return level
    logging.getLogger(APP_LOGGER_NAME).warning(
        "Invalid LOG_LEVEL %r; using %s", name, logging.getLevelName(default)
    )
    return default


def configure_logging(settings: Settings) -> None:
    """Configure stderr (+ optional file) logging once per process."""
    global _configured
    if _configured:
        return

    level = parse_log_level(settings.log_level)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
    ]
    if settings.log_file:
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_path,
                maxBytes=settings.log_file_max_bytes,
                backupCount=settings.log_file_backup_count,
                encoding="utf-8",
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)

    app_logger = logging.getLogger(APP_LOGGER_NAME)
    app_logger.setLevel(level)

    for noisy in ("httpx", "httpcore", "chromadb", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    app_logger.debug(
        "Debug logging enabled (level=%s, file=%s)",
        logging.getLevelName(level),
        settings.log_file or "(stderr only)",
    )


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(name or APP_LOGGER_NAME)


def log_startup_summary(settings: Settings) -> None:
    """Log non-secret configuration at agent startup."""
    logger = get_logger()
    logger.info(
        "Starting agent: ollama_model=%s ollama_host=%s oracle_dsn=%s "
        "chroma_dir=%s chroma_collection=%s audit_enabled=%s",
        settings.ollama_model or "(unset)",
        settings.ollama_host,
        settings.oracle_dsn,
        settings.chroma_persist_directory or "(unset)",
        settings.chroma_collection_name or "(unset)",
        settings.audit_enabled,
    )
    if settings.basic_auth_enabled:
        logger.info("HTTP basic auth enabled for app")
    if settings.admin_auth_enabled:
        logger.info("Signed admin sessions enabled at /admin")
    else:
        logger.warning("Admin reports/training disabled: configure ADMIN_* settings")
    if settings.ollama_basic_auth_enabled:
        logger.info("Ollama basic auth enabled")
