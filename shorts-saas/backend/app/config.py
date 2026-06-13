"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "Shorts SaaS"
    debug: bool = False
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Database
    database_url: str = "postgresql+asyncpg://shorts:shorts@postgres:5432/shorts"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Media storage
    media_dir: str = "/app/media"

    # AI API Keys (platform-managed)
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    recraft_api_key: str = ""
    fal_api_key: str = ""
    elevenlabs_api_key: str = ""
    pexels_api_key: str = ""

    # Whisper model size (base=74MB, small=244MB)
    whisper_model: str = "base"

    # Default credits for new users
    default_credits: int = 5

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
