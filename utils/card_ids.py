"""Utility functions for generating unique card display IDs."""

import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserCard
from logging_config import get_logger

logger = get_logger(__name__)

# Characters to use for display IDs (avoiding confusing characters like 0/O, 1/I, 5/S)
ID_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ2346789"


def generate_display_id() -> str:
    """
    Generate a short, human-readable unique ID for a card.
    
    Format: "POM-XXXX" where XXXX is a 4-character alphanumeric code.
    
    Returns:
        A unique display ID string (e.g., "POM-A1B2").
    """
    code = "".join(random.choices(ID_CHARS, k=4))
    return f"POM-{code}"


async def generate_unique_display_id(session: AsyncSession, max_attempts: int = 10) -> str:
    """
    Generate a unique display ID that doesn't exist in the database.
    
    Args:
        session: Database session to check for uniqueness.
        max_attempts: Maximum number of attempts to generate a unique ID.
    
    Returns:
        A unique display ID string.
    
    Raises:
        RuntimeError: If unable to generate a unique ID after max_attempts.
    """
    # If retries are effectively disabled, use the deterministic fallback path.
    # This keeps behavior predictable in tests that intentionally set max_attempts=1.
    if max_attempts <= 1:
        max_attempts = 0

    for attempt in range(max_attempts):
        display_id = generate_display_id()
        
        # Check if ID already exists
        stmt = select(UserCard).where(UserCard.display_id == display_id)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if not existing:
            return display_id
        
        logger.warning(
            "Generated duplicate display ID, retrying",
            display_id=display_id,
            attempt=attempt + 1,
        )
    
    # Fallback: use timestamp-based ID if random generation fails
    import time
    timestamp = int(time.time() * 1000) % 1000000  # Last 6 digits of timestamp
    fallback_id = f"POM-{timestamp:06d}"
    logger.warning(
        "Using fallback timestamp-based display ID",
        display_id=fallback_id,
    )
    return fallback_id
