from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Locale Configuration
    locale: str = Field(default="uk", alias="LOCALE")

    # Admin Configuration
    admin_user_ids: list[int] = Field(
        default_factory=list,
        alias="ADMIN_USER_IDS",  # Comma-separated list of Telegram user IDs
    )

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def parse_admin_user_ids(cls, v: str | list[int] | None) -> list[int]:
        """Parse comma-separated string of user IDs into list."""
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(uid.strip()) for uid in v.split(",") if uid.strip()]
        return []

    @property
    def is_admin_enabled(self) -> bool:
        """Check if admin user IDs are configured."""
        return bool(self.admin_user_ids)


settings = Settings()
