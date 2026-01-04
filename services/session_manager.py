"""Redis-based session management for trading and battle interactions."""

import json
from typing import Optional
from uuid import uuid4

import redis.asyncio as redis
from redis.asyncio import Redis

from config import settings
from logging_config import get_logger

logger = get_logger(__name__)

# Default TTL for sessions (10 minutes)
DEFAULT_SESSION_TTL = 600


class SessionManager:
    """Manages trade and battle sessions using Redis for state storage."""

    def __init__(self, redis_client: Optional[Redis] = None, default_ttl: int = DEFAULT_SESSION_TTL):
        """
        Initialize SessionManager.

        Args:
            redis_client: Optional Redis client instance. If not provided, creates one from settings.
            default_ttl: Default TTL in seconds for sessions (default: 600 = 10 minutes).
        """
        self._redis: Optional[Redis] = redis_client
        self._default_ttl = default_ttl

    async def _get_redis(self) -> Redis:
        """Get or create Redis client connection."""
        if self._redis is None:
            self._redis = await redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    # Trade Session Methods

    async def create_trade_session(
        self, initiator_id: int, card_id: str, message_id: int, chat_id: int
    ) -> str:
        """
        Create a new trade session.

        Args:
            initiator_id: Telegram user ID of the trade initiator.
            card_id: UUID of the card being offered (as string).
            message_id: Message ID where the trade was initiated.
            chat_id: Chat ID where the trade is happening.

        Returns:
            Session ID (UUID string).
        """
        session_id = str(uuid4())
        key = f"trade:{session_id}"

        session_data = {
            "initiator_id": initiator_id,
            "card_id": card_id,
            "message_id": message_id,
            "chat_id": chat_id,
            "opponent_id": None,
            "opponent_card_id": None,
            "initiator_confirmed": False,
            "opponent_confirmed": False,
            "status": "pending",  # pending, active, completed, cancelled
        }

        client = await self._get_redis()
        try:
            await client.setex(key, self._default_ttl, json.dumps(session_data))
            logger.info(
                "Trade session created",
                session_id=session_id,
                initiator_id=initiator_id,
                card_id=card_id,
            )
            return session_id
        except redis.RedisError as e:
            logger.error(
                "Redis error creating trade session",
                error=str(e),
                exc_info=True,
            )
            raise

    async def get_trade_session(self, session_id: str) -> Optional[dict]:
        """
        Get trade session data.

        Args:
            session_id: Session ID.

        Returns:
            Session data dict or None if not found.
        """
        key = f"trade:{session_id}"
        client = await self._get_redis()

        try:
            data = await client.get(key)
            if data is None:
                return None
            return json.loads(data)
        except (redis.RedisError, json.JSONDecodeError) as e:
            logger.error(
                "Redis error getting trade session",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return None

    async def update_trade_session(
        self, session_id: str, opponent_id: Optional[int] = None, opponent_card_id: Optional[str] = None
    ) -> bool:
        """
        Update trade session with opponent's card selection.

        Args:
            session_id: Session ID.
            opponent_id: Opponent's Telegram user ID.
            opponent_card_id: Opponent's card UUID (as string).

        Returns:
            True if update successful, False otherwise.
        """
        session_data = await self.get_trade_session(session_id)
        if not session_data:
            return False

        if opponent_id is not None:
            session_data["opponent_id"] = opponent_id
        if opponent_card_id is not None:
            session_data["opponent_card_id"] = opponent_card_id

        key = f"trade:{session_id}"
        client = await self._get_redis()

        try:
            # Get remaining TTL to preserve it
            ttl = await client.ttl(key)
            if ttl > 0:
                await client.setex(key, ttl, json.dumps(session_data))
            else:
                await client.setex(key, self._default_ttl, json.dumps(session_data))
            logger.debug("Trade session updated", session_id=session_id)
            return True
        except redis.RedisError as e:
            logger.error(
                "Redis error updating trade session",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return False

    async def confirm_trade(self, session_id: str, user_id: int) -> bool:
        """
        Mark a user's confirmation in trade session.

        Args:
            session_id: Session ID.
            user_id: User ID confirming the trade.

        Returns:
            True if both users confirmed (trade ready), False otherwise.
        """
        session_data = await self.get_trade_session(session_id)
        if not session_data:
            return False

        if session_data["initiator_id"] == user_id:
            session_data["initiator_confirmed"] = True
        elif session_data.get("opponent_id") == user_id:
            session_data["opponent_confirmed"] = True
        else:
            logger.warning(
                "User not part of trade session",
                session_id=session_id,
                user_id=user_id,
            )
            return False

        key = f"trade:{session_id}"
        client = await self._get_redis()

        try:
            ttl = await client.ttl(key)
            if ttl > 0:
                await client.setex(key, ttl, json.dumps(session_data))
            else:
                await client.setex(key, self._default_ttl, json.dumps(session_data))

            # Check if both confirmed
            both_confirmed = (
                session_data["initiator_confirmed"] and session_data["opponent_confirmed"]
            )
            if both_confirmed:
                session_data["status"] = "completed"
                await client.setex(key, ttl if ttl > 0 else self._default_ttl, json.dumps(session_data))

            return both_confirmed
        except redis.RedisError as e:
            logger.error(
                "Redis error confirming trade",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return False

    async def delete_trade_session(self, session_id: str) -> bool:
        """
        Delete trade session.

        Args:
            session_id: Session ID.

        Returns:
            True if deleted, False if not found.
        """
        key = f"trade:{session_id}"
        client = await self._get_redis()

        try:
            deleted = await client.delete(key)
            if deleted:
                logger.debug("Trade session deleted", session_id=session_id)
            return bool(deleted)
        except redis.RedisError as e:
            logger.error(
                "Redis error deleting trade session",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return False

    # Battle Session Methods

    async def create_battle_session(
        self,
        challenger_id: int,
        opponent_id: int,
        message_id: int,
        chat_id: int,
    ) -> str:
        """
        Create a new battle session.

        Args:
            challenger_id: Telegram user ID of the challenger.
            opponent_id: Telegram user ID of the opponent.
            message_id: Message ID where the challenge was sent.
            chat_id: Chat ID where the battle is happening.

        Returns:
            Session ID (UUID string).
        """
        session_id = str(uuid4())
        key = f"battle:{session_id}"

        session_data = {
            "challenger_id": challenger_id,
            "opponent_id": opponent_id,
            "message_id": message_id,
            "chat_id": chat_id,
            "stake": None,
            "challenger_stake_confirmed": False,
            "opponent_stake_confirmed": False,
            "challenger_deck": [],  # List of card IDs
            "opponent_deck": [],  # List of card IDs
            "status": "pending",  # pending, stake_set, decks_selected, completed, cancelled
        }

        client = await self._get_redis()
        try:
            await client.setex(key, self._default_ttl, json.dumps(session_data))
            logger.info(
                "Battle session created",
                session_id=session_id,
                challenger_id=challenger_id,
                opponent_id=opponent_id,
            )
            return session_id
        except redis.RedisError as e:
            logger.error(
                "Redis error creating battle session",
                error=str(e),
                exc_info=True,
            )
            raise

    async def get_battle_session(self, session_id: str) -> Optional[dict]:
        """
        Get battle session data.

        Args:
            session_id: Session ID.

        Returns:
            Session data dict or None if not found.
        """
        key = f"battle:{session_id}"
        client = await self._get_redis()

        try:
            data = await client.get(key)
            if data is None:
                return None
            return json.loads(data)
        except (redis.RedisError, json.JSONDecodeError) as e:
            logger.error(
                "Redis error getting battle session",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return None

    async def set_battle_stake(self, session_id: str, stake: int) -> bool:
        """
        Set battle stake amount.

        Args:
            session_id: Session ID.
            stake: Stake amount in scraps.

        Returns:
            True if successful, False otherwise.
        """
        session_data = await self.get_battle_session(session_id)
        if not session_data:
            return False

        session_data["stake"] = stake

        key = f"battle:{session_id}"
        client = await self._get_redis()

        try:
            ttl = await client.ttl(key)
            if ttl > 0:
                await client.setex(key, ttl, json.dumps(session_data))
            else:
                await client.setex(key, self._default_ttl, json.dumps(session_data))
            logger.debug("Battle stake set", session_id=session_id, stake=stake)
            return True
        except redis.RedisError as e:
            logger.error(
                "Redis error setting battle stake",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return False

    async def confirm_battle_stake(self, session_id: str, user_id: int) -> bool:
        """
        Mark a user's stake confirmation.

        Args:
            session_id: Session ID.
            user_id: User ID confirming the stake.

        Returns:
            True if both users confirmed stake, False otherwise.
        """
        session_data = await self.get_battle_session(session_id)
        if not session_data:
            return False

        if session_data["challenger_id"] == user_id:
            session_data["challenger_stake_confirmed"] = True
        elif session_data["opponent_id"] == user_id:
            session_data["opponent_stake_confirmed"] = True
        else:
            logger.warning(
                "User not part of battle session",
                session_id=session_id,
                user_id=user_id,
            )
            return False

        key = f"battle:{session_id}"
        client = await self._get_redis()

        try:
            ttl = await client.ttl(key)
            if ttl > 0:
                await client.setex(key, ttl, json.dumps(session_data))
            else:
                await client.setex(key, self._default_ttl, json.dumps(session_data))

            # Check if both confirmed
            both_confirmed = (
                session_data["challenger_stake_confirmed"]
                and session_data["opponent_stake_confirmed"]
            )
            if both_confirmed:
                session_data["status"] = "stake_set"
                await client.setex(key, ttl if ttl > 0 else self._default_ttl, json.dumps(session_data))

            return both_confirmed
        except redis.RedisError as e:
            logger.error(
                "Redis error confirming battle stake",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return False

    async def add_card_to_deck(self, session_id: str, user_id: int, card_id: str) -> tuple[bool, int]:
        """
        Add a card to user's deck in battle session.

        Args:
            session_id: Session ID.
            user_id: User ID adding the card.
            card_id: Card UUID (as string).

        Returns:
            Tuple of (success, current_deck_size).
        """
        session_data = await self.get_battle_session(session_id)
        if not session_data:
            return (False, 0)

        deck_key = "challenger_deck" if session_data["challenger_id"] == user_id else "opponent_deck"
        deck = session_data[deck_key]

        if len(deck) >= 3:
            logger.warning(
                "Deck already full",
                session_id=session_id,
                user_id=user_id,
            )
            return (False, len(deck))

        if card_id in deck:
            logger.warning(
                "Card already in deck",
                session_id=session_id,
                user_id=user_id,
                card_id=card_id,
            )
            return (False, len(deck))

        deck.append(card_id)
        session_data[deck_key] = deck

        # Update status if both decks are ready
        if len(session_data["challenger_deck"]) == 3 and len(session_data["opponent_deck"]) == 3:
            session_data["status"] = "decks_selected"

        key = f"battle:{session_id}"
        client = await self._get_redis()

        try:
            ttl = await client.ttl(key)
            if ttl > 0:
                await client.setex(key, ttl, json.dumps(session_data))
            else:
                await client.setex(key, self._default_ttl, json.dumps(session_data))
            logger.debug(
                "Card added to deck",
                session_id=session_id,
                user_id=user_id,
                card_id=card_id,
                deck_size=len(deck),
            )
            return (True, len(deck))
        except redis.RedisError as e:
            logger.error(
                "Redis error adding card to deck",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return (False, len(deck))

    async def delete_battle_session(self, session_id: str) -> bool:
        """
        Delete battle session.

        Args:
            session_id: Session ID.

        Returns:
            True if deleted, False if not found.
        """
        key = f"battle:{session_id}"
        client = await self._get_redis()

        try:
            deleted = await client.delete(key)
            if deleted:
                logger.debug("Battle session deleted", session_id=session_id)
            return bool(deleted)
        except redis.RedisError as e:
            logger.error(
                "Redis error deleting battle session",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return False

    # Blueprint Storage Methods (for autocard callbacks)

    async def store_blueprint(self, blueprint_data: dict, ttl: int = 3600) -> str:
        """
        Store blueprint data in Redis for autocard callbacks.

        Args:
            blueprint_data: Blueprint data dictionary.
            ttl: Time to live in seconds (default: 3600 = 1 hour).

        Returns:
            Blueprint ID (UUID string).
        """
        blueprint_id = str(uuid4())
        key = f"blueprint:{blueprint_id}"
        client = await self._get_redis()

        try:
            await client.setex(key, ttl, json.dumps(blueprint_data))
            logger.debug("Blueprint stored", blueprint_id=blueprint_id)
            return blueprint_id
        except redis.RedisError as e:
            logger.error(
                "Redis error storing blueprint",
                error=str(e),
                exc_info=True,
            )
            raise

    async def update_blueprint(self, blueprint_id: str, blueprint_data: dict, ttl: int | None = None) -> bool:
        """
        Update an existing blueprint data entry in Redis.

        NOTE: This differs from store_blueprint(), which always creates a NEW blueprint_id.

        Args:
            blueprint_id: Existing blueprint ID (UUID string).
            blueprint_data: Updated blueprint data dictionary.
            ttl: Optional TTL in seconds. If None, preserves existing TTL when possible,
                 otherwise defaults to 3600 seconds.

        Returns:
            True if updated successfully, False otherwise.
        """
        key = f"blueprint:{blueprint_id}"
        client = await self._get_redis()

        try:
            ttl_to_use: int
            if ttl is not None:
                ttl_to_use = ttl
            else:
                existing_ttl = await client.ttl(key)
                ttl_to_use = existing_ttl if existing_ttl and existing_ttl > 0 else 3600

            await client.setex(key, ttl_to_use, json.dumps(blueprint_data))
            logger.debug("Blueprint updated", blueprint_id=blueprint_id, ttl=ttl_to_use)
            return True
        except redis.RedisError as e:
            logger.error(
                "Redis error updating blueprint",
                blueprint_id=blueprint_id,
                error=str(e),
                exc_info=True,
            )
            return False

    async def get_blueprint(self, blueprint_id: str) -> Optional[dict]:
        """
        Get blueprint data from Redis.

        Args:
            blueprint_id: Blueprint ID (UUID string).

        Returns:
            Blueprint data dict or None if not found.
        """
        key = f"blueprint:{blueprint_id}"
        client = await self._get_redis()

        try:
            data = await client.get(key)
            if data is None:
                return None
            return json.loads(data)
        except (redis.RedisError, json.JSONDecodeError) as e:
            logger.error(
                "Redis error getting blueprint",
                blueprint_id=blueprint_id,
                error=str(e),
                exc_info=True,
            )
            return None

    async def delete_blueprint(self, blueprint_id: str) -> bool:
        """
        Delete blueprint data from Redis.

        Args:
            blueprint_id: Blueprint ID (UUID string).

        Returns:
            True if deleted, False if not found.
        """
        key = f"blueprint:{blueprint_id}"
        client = await self._get_redis()

        try:
            deleted = await client.delete(key)
            return bool(deleted)
        except redis.RedisError as e:
            logger.error(
                "Redis error deleting blueprint",
                blueprint_id=blueprint_id,
                error=str(e),
                exc_info=True,
            )
            return False

    async def close(self) -> None:
        """Close Redis connection if it was created by this instance."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    # Turn-Based Battle State Methods

    async def save_turn_battle_state(self, state) -> bool:
        """
        Save the complete BattleState (Pydantic model).
        
        Args:
            state: BattleState instance (from services.turn_battle).
            
        Returns:
            True if successful.
        """
        key = f"turn_battle:{state.session_id}"
        client = await self._get_redis()
        
        try:
            # Serialize Pydantic model to JSON string
            data = state.model_dump_json()
            await client.setex(key, self._default_ttl, data)
            logger.debug("Battle state saved", session_id=state.session_id)
            return True
        except Exception as e:
            logger.error(
                "Error saving battle state",
                session_id=state.session_id,
                error=str(e),
                exc_info=True,
            )
            return False

    async def get_turn_battle_state(self, session_id: str):
        """
        Retrieve BattleState.
        
        Returns:
            BattleState instance or None.
        """
        from services.turn_battle import BattleState # Import here to avoid circular dependency top-level
        
        key = f"turn_battle:{session_id}"
        client = await self._get_redis()
        
        try:
            data = await client.get(key)
            if not data:
                return None
            return BattleState.model_validate_json(data)
        except Exception as e:
            logger.error(
                "Error loading battle state",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )
            return None
