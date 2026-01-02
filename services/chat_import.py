"""Service for importing chat history from Telegram JSON exports."""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database.models import GroupChat, MessageLog, User
from database.session import get_session
from logging_config import get_logger

logger = get_logger(__name__)


class ChatImportService:
    """Service for importing Telegram chat exports into MessageLog."""

    def __init__(self, export_dir: str = "data/chat_exports"):
        """
        Initialize ChatImportService.

        Args:
            export_dir: Directory containing chat export JSON files.
        """
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    async def import_telegram_json(
        self, filename: str, progress_callback: Callable[[str], Awaitable[None]] | None = None
    ) -> dict[str, Any]:
        """
        Import messages from Telegram Desktop JSON export.

        Args:
            filename: Name of the JSON file in export directory.
            progress_callback: Optional callback function(status_text: str) to update progress.

        Returns:
            Dictionary with import statistics.
        """
        file_path = self.export_dir / filename

        if not file_path.exists():
            raise FileNotFoundError(f"Export file not found: {file_path}")

        logger.info("Starting chat import", filename=filename)

        # Load JSON file
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON file", filename=filename, error=str(e))
            raise ValueError(f"Invalid JSON file: {e}")

        # Extract chat info from top level
        chat_id = data.get("id")
        chat_name = data.get("name", "Unknown Chat")
        chat_type = data.get("type", "unknown")
        
        # Convert chat_id to integer if needed
        if isinstance(chat_id, str):
            if chat_id.startswith("chat") or chat_id.startswith("channel"):
                chat_id = int(chat_id.replace("chat", "").replace("channel", ""))
            else:
                try:
                    chat_id = int(chat_id)
                except (ValueError, TypeError):
                    logger.error("Could not parse chat ID from export", chat_id=chat_id)
                    raise ValueError(f"Invalid chat ID: {chat_id}")
        elif not isinstance(chat_id, int):
            logger.error("Chat ID is not a valid integer", chat_id=chat_id, chat_id_type=type(chat_id))
            raise ValueError(f"Invalid chat ID type: {type(chat_id)}")

        # Parse messages
        messages = data.get("messages", [])
        total_messages = len(messages)
        if not messages:
            logger.warning("No messages found in export", filename=filename)
            return {
                "messages_imported": 0,
                "users_created": 0,
                "chats_created": 0,
                "errors": 0,
            }

        stats = {
            "messages_imported": 0,
            "users_created": 0,
            "chats_created": 0,
            "errors": 0,
        }

        # Initial progress update
        if progress_callback:
            await progress_callback(
                f"📥 **Імпорт чату**\n\n"
                f"📄 Файл: `{filename}`\n"
                f"💬 Всього повідомлень: {total_messages:,}\n"
                f"⏳ Завантаження даних...",
            )

        # Process messages in batches
        batch_size = 100
        user_cache: dict[int, dict[str, Any]] = {}  # Map user_id -> user_data (including username if found)
        chat_created = False
        last_update = 0
        update_interval = 10000  # Update every 10000 messages (reduced frequency to avoid rate limits)
        last_update_time = 0
        min_update_interval_seconds = 5  # Minimum 5 seconds between updates

        async for session in get_session():
            try:
                # Create chat first
                if not chat_created:
                    try:
                        stmt = insert(GroupChat).values(
                            chat_id=chat_id,
                            title=chat_name,
                            is_active=True,
                        )
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["chat_id"],
                            set_={"title": chat_name, "is_active": True}
                        )
                        await session.execute(stmt)
                        stats["chats_created"] = 1
                        chat_created = True
                        
                        if progress_callback:
                            await progress_callback(
                                f"📥 **Імпорт чату**\n\n"
                                f"📄 Файл: `{filename}`\n"
                                f"💬 Всього повідомлень: {total_messages:,}\n"
                                f"✅ Чат створено: {chat_name}\n"
                                f"⏳ Обробка повідомлень...",
                            )
                    except Exception as e:
                        logger.warning(
                            "Error inserting chat",
                            chat_id=chat_id,
                            error=str(e),
                        )

                for i in range(0, len(messages), batch_size):
                    batch = messages[i : i + batch_size]
                    batch_logs: list[dict[str, Any]] = []

                    for msg in batch:
                        try:
                            # Skip non-message types
                            if msg.get("type") != "message":
                                continue

                            # Extract message data
                            from_id_str = msg.get("from_id")
                            if not from_id_str:
                                continue

                            # Parse from_id (format: "user123456789" or "channel123456789")
                            if from_id_str.startswith("user"):
                                user_id = int(from_id_str.replace("user", ""))
                            elif from_id_str.startswith("channel"):
                                # Skip channel messages for now
                                continue
                            else:
                                # Try direct integer
                                try:
                                    user_id = int(from_id_str)
                                except ValueError:
                                    stats["errors"] += 1
                                    continue

                            # Use chat ID from top level (already extracted above)
                            # All messages in this export belong to the same chat

                            # Get message text
                            text = msg.get("text", "")
                            if isinstance(text, list):
                                # Telegram exports sometimes have text as array of objects
                                text_parts = []
                                for part in text:
                                    if isinstance(part, str):
                                        text_parts.append(part)
                                    elif isinstance(part, dict):
                                        text_parts.append(part.get("text", ""))
                                text = " ".join(text_parts)
                            
                            if not text or not text.strip():
                                continue

                            # Try to extract username from message metadata
                            # Check "from" field - it might be a display name, not username
                            from_name = msg.get("from", "")
                            potential_username = None
                            
                            # Look for username in message text mentions (if this user mentioned themselves)
                            # Extract all @mentions from text
                            mentions = re.findall(r'@(\w+)', text) if text else []
                            
                            # Check if "from" field looks like a username
                            if from_name and isinstance(from_name, str):
                                from_name_clean = from_name.strip()
                                # If it starts with @, it's already a username
                                if from_name_clean.startswith("@"):
                                    potential_username = from_name_clean[1:].strip()
                                # Otherwise, check if it's a simple alphanumeric string (might be username)
                                elif re.match(r'^[a-zA-Z0-9_]+$', from_name_clean):
                                    potential_username = from_name_clean
                            
                            # Also check text_entities if available (Telegram exports sometimes have structured entities)
                            text_entities = msg.get("text_entities", [])
                            if not potential_username and text_entities:
                                for entity in text_entities:
                                    if entity.get("type") == "mention" and entity.get("text"):
                                        mention_text = entity.get("text", "").strip()
                                        if mention_text.startswith("@"):
                                            potential_username = mention_text[1:].strip()
                                            break

                            # Parse date
                            date_str = msg.get("date", "")
                            try:
                                if isinstance(date_str, str):
                                    # Try ISO format first
                                    try:
                                        created_at = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                                    except ValueError:
                                        # Try other formats
                                        try:
                                            created_at = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                                            created_at = created_at.replace(tzinfo=timezone.utc)
                                        except ValueError:
                                            # Fallback to current time
                                            created_at = datetime.now(timezone.utc)
                                else:
                                    # Assume timestamp
                                    created_at = datetime.fromtimestamp(date_str, tz=timezone.utc)
                            except (ValueError, TypeError):
                                # Use current time as fallback
                                created_at = datetime.now(timezone.utc)

                            # Cache user with username if found
                            if user_id not in user_cache:
                                user_cache[user_id] = {
                                    "telegram_id": user_id,
                                    "username": potential_username,  # May be None
                                    "balance": 0,
                                }
                            # Update username if we found one and didn't have it before
                            elif potential_username and not user_cache[user_id].get("username"):
                                user_cache[user_id]["username"] = potential_username

                            # Prepare message log entry
                            batch_logs.append({
                                "user_id": user_id,
                                "chat_id": chat_id,
                                "content": text[:500],  # Truncate to 500 chars
                                "created_at": created_at,
                            })

                        except Exception as e:
                            logger.warning(
                                "Error processing message",
                                message_id=msg.get("id"),
                                error=str(e),
                            )
                            stats["errors"] += 1
                            continue

                    # Bulk insert/update users from cache (after collecting all users in batch)
                    # We'll do this after processing all messages to avoid duplicate checks

                    # Ensure all users from this batch exist before inserting messages
                    if batch_logs:
                        # Get all unique user_ids from batch_logs
                        batch_user_ids = {log_entry["user_id"] for log_entry in batch_logs}
                        
                        # Create any missing users
                        for user_id in batch_user_ids:
                            if user_id not in user_cache:
                                # User not seen before, create with minimal data
                                user_cache[user_id] = {
                                    "telegram_id": user_id,
                                    "username": None,
                                    "balance": 0,
                                }
                        
                        # Bulk insert/update users for this batch using ON CONFLICT
                        # Users are created automatically from message logs - no registration required
                        users_to_insert = [user_cache[user_id] for user_id in batch_user_ids]
                        
                        if users_to_insert:
                            try:
                                # Check which users already exist BEFORE insert (for accurate counting)
                                user_ids_to_check = [u["telegram_id"] for u in users_to_insert]
                                existing_user_ids_stmt = select(User.telegram_id).where(
                                    User.telegram_id.in_(user_ids_to_check)
                                )
                                existing_result = await session.execute(existing_user_ids_stmt)
                                existing_user_ids_before = {row[0] for row in existing_result.all()}
                                
                                # Use bulk insert with ON CONFLICT DO NOTHING for new users
                                # and ON CONFLICT DO UPDATE for username updates
                                stmt = insert(User).values(users_to_insert)
                                
                                # Update username if we found one, but don't overwrite existing usernames
                                stmt = stmt.on_conflict_do_update(
                                    index_elements=["telegram_id"],
                                    set_={
                                        "username": stmt.excluded.username
                                    },
                                    where=User.username.is_(None)  # Only update if username is NULL
                                )
                                
                                await session.execute(stmt)
                                
                                # Count new users (those that didn't exist before)
                                new_users_in_batch = len(user_ids_to_check) - len(existing_user_ids_before)
                                if new_users_in_batch > 0:
                                    stats["users_created"] += new_users_in_batch
                                    logger.debug(
                                        "Users created in batch",
                                        new_count=new_users_in_batch,
                                        total_in_batch=len(user_ids_to_check),
                                    )
                                        
                            except Exception as e:
                                logger.warning(
                                    "Error bulk inserting users, falling back to individual inserts",
                                    error=str(e),
                                    user_count=len(users_to_insert),
                                    exc_info=True,
                                )
                                # Fallback to individual inserts with proper counting
                                for user_id in batch_user_ids:
                                    user_data = user_cache[user_id]
                                    try:
                                        # Check if exists first
                                        check_stmt = select(User.telegram_id).where(User.telegram_id == user_id)
                                        check_result = await session.execute(check_stmt)
                                        exists = check_result.scalar_one_or_none() is not None
                                        
                                        if not exists:
                                            stats["users_created"] += 1
                                        
                                        stmt = insert(User).values(**user_data)
                                        stmt = stmt.on_conflict_do_update(
                                            index_elements=["telegram_id"],
                                            set_={"username": stmt.excluded.username},
                                            where=User.username.is_(None)
                                        )
                                        await session.execute(stmt)
                                    except Exception as e2:
                                        logger.warning(
                                            "Error inserting user (fallback)",
                                            user_id=user_id,
                                            error=str(e2),
                                        )
                        
                        # Now insert message logs (all users should exist)
                        for log_entry in batch_logs:
                            try:
                                message_log = MessageLog(**log_entry)
                                session.add(message_log)
                                stats["messages_imported"] += 1
                            except Exception as e:
                                logger.warning(
                                    "Error inserting message log",
                                    user_id=log_entry.get("user_id"),
                                    error=str(e),
                                )
                                stats["errors"] += 1

                    await session.commit()

                    # Update progress periodically (with rate limiting)
                    current_time = time.time()
                    if progress_callback and (
                        (stats["messages_imported"] - last_update >= update_interval) or
                        (current_time - last_update_time >= min_update_interval_seconds)
                    ):
                        progress_pct = int((stats["messages_imported"] / total_messages) * 100) if total_messages > 0 else 0
                        try:
                            await progress_callback(
                                f"📥 **Імпорт чату**\n\n"
                                f"📄 Файл: `{filename}`\n"
                                f"💬 Оброблено: {stats['messages_imported']:,} / {total_messages:,} ({progress_pct}%)\n"
                                f"👤 Користувачів знайдено: {len(user_cache)}\n"
                                f"⏳ Продовжується...",
                            )
                            last_update = stats["messages_imported"]
                            last_update_time = current_time
                        except Exception as e:
                            # Silently ignore rate limit errors
                            logger.debug("Progress update skipped", error=str(e))

                # Final pass: Update usernames for users that might have been found later
                # Most users should already be created during batch processing
                # This pass only updates usernames for users where we found one
                if user_cache:
                    async for session in get_session():
                        try:
                            # Bulk update usernames where we found them
                            users_with_usernames = {
                                uid: data for uid, data in user_cache.items()
                                if data.get("username")
                            }
                            
                            if users_with_usernames:
                                for user_id, user_data in users_with_usernames.items():
                                    try:
                                        # Update username if user exists and doesn't have one
                                        update_stmt = (
                                            select(User)
                                            .where(User.telegram_id == user_id)
                                            .where(User.username.is_(None))
                                        )
                                        result = await session.execute(update_stmt)
                                        user = result.scalar_one_or_none()
                                        
                                        if user:
                                            user.username = user_data["username"]
                                            session.add(user)
                                        
                                        await session.commit()
                                    except Exception as e:
                                        logger.warning(
                                            "Error updating username",
                                            user_id=user_id,
                                            error=str(e),
                                        )
                                        await session.rollback()
                        except Exception as e:
                            logger.error(
                                "Error in final username update pass",
                                error=str(e),
                                exc_info=True,
                            )
                        break

                logger.info(
                    "Chat import completed",
                    filename=filename,
                    **stats,
                )

            except Exception as e:
                logger.error(
                    "Error during chat import",
                    filename=filename,
                    error=str(e),
                    exc_info=True,
                )
                await session.rollback()
                raise
            break

        return stats
