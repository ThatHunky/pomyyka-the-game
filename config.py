from typing import Optional

from pydantic import Field
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


settings = Settings()
