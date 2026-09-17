"""Oracle persistence for AI response notifications."""

from __future__ import annotations

import logging
from datetime import datetime

import oracledb

from .settings import Settings

logger = logging.getLogger(__name__)


class AiNotificationWriter:
    """Insert one row in ATFM.T_NOTIFICATION for each completed AI turn."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def write(
        self, *, question: str, completed: bool, response_at: datetime
    ) -> None:
        status = "đã hoàn thành" if completed else "chưa hoàn thành"
        connection = None
        cursor = None
        try:
            connection = oracledb.connect(
                user=self.settings.oracle_user,
                password=self.settings.oracle_password,
                dsn=self.settings.oracle_dsn,
            )
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO ATFM.T_NOTIFICATION
                    (TITLE, CONTENT, DATETIME, SOURCE_TYPE)
                VALUES (:title, :content, :notification_datetime, :source_type)
                """,
                title="AI response",
                content=f"Câu hỏi: {question}\nTrạng thái: {status}",
                notification_datetime=response_at.replace(tzinfo=None),
                source_type="AI",
            )
            connection.commit()
        except Exception:
            logger.exception("Could not insert AI notification")
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()
