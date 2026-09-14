from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN : str

    DATABASE_URL : str

    REDIS_URL : str

    LLM_API_KEY : str

    LLM_MODEL : str

    CF_API_BASE : str

    LEETCODE_API_BASE : str

    MORNING_SEND_TIME : str

    EVENING_SEND_TIME : str

    TRIAL_DAYS : int

    STARS_PRICE : int

    SUBSCRIPTION_DAYS : int

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()