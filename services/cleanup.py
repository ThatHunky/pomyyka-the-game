"""Cleanup service for removing old message logs."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete

from database.models import MessageLog
from database.session import get_session
from logging_config import get_logger

logger = get_logger(__name__)


class CleanupService:
    """Service for cleaning up old message logs."""

    def __init__(self, retention_days: int = 7):
        """
        Initialize CleanupService.

        Args:
            retention_days: Number of days to retain messages (default: 7).
        """
        self._retention_days = retention_days
        self._scheduler: Optional[AsyncIOScheduler] = None

    async def start(self) -> None:
        """Start the cleanup scheduler."""
        if self._scheduler is not None:
            logger.warning("Cleanup scheduler already started")
            return

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._cleanup_old_logs,
            "cron",
            hour=0,  # Run at midnight
            minute=0,
            id="cleanup_message_logs",
            replace_existing=True,
        )
        self._scheduler.start()

        logger.info(
            "Cleanup scheduler started",
            retention_days=self._retention_days,
        )

    async def stop(self) -> None:
        """Stop the cleanup scheduler."""
        if self._scheduler is None:
            return

        self._scheduler.shutdown(wait=True)
        self._scheduler = None
        logger.info("Cleanup scheduler stopped")

    async def _cleanup_old_logs(self) -> None:
        """Delete message logs older than retention period."""
        logger.debug("Starting message log cleanup job")

        try:
            async for session in get_session():
                # Calculate cutoff date
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=self._retention_days)

                # Delete old logs
                stmt = delete(MessageLog).where(MessageLog.created_at < cutoff_date)
                result = await session.execute(stmt)
                # Session will be committed automatically by get_session()

                deleted_count = result.rowcount
                logger.info(
                    "Message log cleanup completed",
                    deleted_count=deleted_count,
                    cutoff_date=cutoff_date.isoformat(),
                )

        except Exception as e:
            logger.error(
                "Error in cleanup_old_logs job",
                error=str(e),
                exc_info=True,
            )
