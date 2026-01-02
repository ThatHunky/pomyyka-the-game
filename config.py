import logging
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram Bot Configuration
    bot_token: str = Field(..., alias="BOT_TOKEN")

    # Database Configuration
    db_url: str = Field(..., alias="DB_URL")

    # Redis Configuration
    redis_url: str = Field(..., alias="REDIS_URL")

    # Google Gemini API (Optional)
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")

    # Model Constants
    # Gemini 3.0 Flash (Preview) - Fast reasoning model with "Thinking" modality
    text_model_id: str = Field(default="gemini-3-flash-preview", alias="TEXT_MODEL_ID")
    # Gemini 3.0 Pro Image (Preview) - Nano Banana Pro with "Image Generation" modality
    image_model_id: str = Field(
        default="gemini-3-pro-image-preview", alias="IMAGE_MODEL_ID"
    )

    # Locale Configuration
    locale: str = Field(default="uk", alias="LOCALE")

    # Admin Configuration
    admin_user_ids: list[int] = Field(
        default_factory=list,
        alias="ADMIN_USER_IDS",  # Comma-separated list of Telegram user IDs
    )

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def parse_admin_user_ids(cls, v: str | int | list[int] | None) -> list[int]:
        """Parse comma-separated string of user IDs into list."""
        if v is None:
            logger.debug("ADMIN_USER_IDS is None, returning empty list")
            return []
        if isinstance(v, list):
            logger.debug(f"ADMIN_USER_IDS is already a list: {v}")
            return v
        if isinstance(v, int):
            logger.debug(f"ADMIN_USER_IDS is a single int: {v}")
            return [v]
        if isinstance(v, str):
            logger.debug(f"ADMIN_USER_IDS raw string value: {repr(v)}")
            # Remove quotes if present and strip whitespace
            v = v.strip().strip('"').strip("'")
            if not v:
                logger.debug("ADMIN_USER_IDS is empty after stripping, returning empty list")
                return []
            # Split by comma and convert to int, filtering out empty strings
            result = []
            for uid in v.split(","):
                uid_clean = uid.strip().strip('"').strip("'")
                if uid_clean:
                    try:
                        result.append(int(uid_clean))
                    except ValueError as e:
                        # Skip invalid entries but don't fail completely
                        logger.warning(f"Invalid admin user ID '{uid_clean}': {e}")
                        continue
            logger.info(f"Parsed ADMIN_USER_IDS: {result}")
            return result
        logger.warning(f"ADMIN_USER_IDS has unexpected type: {type(v)}")
        return []

    @property
    def is_admin_enabled(self) -> bool:
        """Check if admin user IDs are configured."""
        return bool(self.admin_user_ids)


settings = Settings()
