import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel


class Settings(BaseModel):
    # General
    app_name: str = "Buddy – Mattermost Onboarding Agent"
    debug: bool = bool(int(os.getenv("DEBUG", "0")))

    # Mattermost
    mattermost_base_url: str = os.getenv("MATTERMOST_BASE_URL", "http://localhost:8065")
    mattermost_bot_token: str = os.getenv("MATTERMOST_BOT_TOKEN", "")
    mattermost_expert_channel_id: str = os.getenv("MATTERMOST_EXPERT_CHANNEL_ID", "")

    # Database
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./buddy.db")

    # LLM (OpenRouter by default)
    llm_provider: str = os.getenv("LLM_PROVIDER", "openrouter")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")


@lru_cache()
def get_settings() -> Settings:
    # Загружаем переменные из .env один раз при первом вызове
    load_dotenv()
    return Settings()

