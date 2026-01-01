"""Redis-based locking mechanism for preventing drop claim race conditions."""

from typing import Optional

import redis.asyncio as redis
from redis.asyncio import Redis

from config import settings
from logging_config import get_logger

logger = get_logger(__name__)

# Lua script for atomic drop claim operation
# Returns 1 if claim successful, 0 if already claimed
CLAIM_DROP_SCRIPT = """
local key = KEYS[1]
local user_id = ARGV[1]
local ttl = ARGV[2]

-- Check if key exists
local exists = redis.call('EXISTS', key)

if exists == 0 then
    -- Key doesn't exist, claim it
    redis.call('SET', key, user_id)
    redis.call('EXPIRE', key, ttl)
    return 1
else
    -- Key already exists, claim failed
    return 0
end
"""


class DropManager:
    """Manages drop claims using Redis for atomic operations."""

    def __init__(self, redis_client: Optional[Redis] = None, default_ttl: int = 300):
        """
        Initialize DropManager.

        Args:
            redis_client: Optional Redis client instance. If not provided, creates one from settings.
            default_ttl: Default TTL in seconds for drop claims (default: 300 = 5 minutes).
        """
        self._redis: Optional[Redis] = redis_client
        self._default_ttl = default_ttl
        self._script_sha: Optional[str] = None

    async def _get_redis(self) -> Redis:
        """Get or create Redis client connection."""
        if self._redis is None:
            self._redis = await redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def _ensure_script_loaded(self) -> str:
        """
        Ensure Lua script is loaded and return its SHA.

        Returns:
            SHA hash of the loaded script.
        """
        client = await self._get_redis()
        if self._script_sha is None:
            self._script_sha = await client.script_load(CLAIM_DROP_SCRIPT)
        return self._script_sha

    async def try_claim_drop(self, message_id: int, user_id: int, ttl: Optional[int] = None) -> bool:
        """
        Attempt to atomically claim a drop for a user.

        This operation is atomic and prevents race conditions when multiple users
        try to claim the same drop simultaneously.

        Args:
            message_id: The message ID of the drop.
            user_id: The user ID attempting to claim the drop.
            ttl: Optional TTL in seconds. If not provided, uses default_ttl.

        Returns:
            True if claim was successful, False if drop was already claimed.
        """
        if ttl is None:
            ttl = self._default_ttl

        # Ensure ttl is an integer (redis-py 5.2.0 is strict about types)
        ttl = int(ttl)

        key = f"drop:{message_id}"
        script_sha = await self._ensure_script_loaded()
        client = await self._get_redis()

        try:
            result = await client.evalsha(
                script_sha,
                1,  # Number of keys
                key,  # KEYS[1]
                str(user_id),  # ARGV[1]
                str(ttl),  # ARGV[2]
            )

            # Lua script returns 1 for success, 0 for failure
            claimed = result == 1

            if claimed:
                logger.info(
                    "Drop claimed successfully",
                    message_id=message_id,
                    user_id=user_id,
                    ttl=ttl,
                )
            else:
                logger.debug(
                    "Drop already claimed",
                    message_id=message_id,
                    user_id=user_id,
                )

            return claimed

        except redis.RedisError as e:
            logger.error(
                "Redis error during drop claim",
                message_id=message_id,
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            # On Redis error, fail safe: return False to prevent double claims
            return False

    async def release_drop(self, message_id: int) -> bool:
        """
        Release a drop claim (delete the key).

        Useful for cleanup or manual release scenarios.

        Args:
            message_id: The message ID of the drop to release.

        Returns:
            True if key was deleted, False if key didn't exist.
        """
        key = f"drop:{message_id}"
        client = await self._get_redis()

        try:
            deleted = await client.delete(key)
            if deleted:
                logger.debug("Drop released", message_id=message_id)
            return bool(deleted)

        except redis.RedisError as e:
            logger.error(
                "Redis error during drop release",
                message_id=message_id,
                error=str(e),
                exc_info=True,
            )
            return False

    async def get_claim_owner(self, message_id: int) -> Optional[int]:
        """
        Get the user ID who claimed a drop, if any.

        Args:
            message_id: The message ID of the drop.

        Returns:
            User ID if drop is claimed, None otherwise.
        """
        key = f"drop:{message_id}"
        client = await self._get_redis()

        try:
            value = await client.get(key)
            if value is None:
                return None
            return int(value)

        except (redis.RedisError, ValueError) as e:
            logger.error(
                "Redis error getting claim owner",
                message_id=message_id,
                error=str(e),
                exc_info=True,
            )
            return None

    async def close(self) -> None:
        """Close Redis connection if it was created by this instance."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            self._script_sha = None
