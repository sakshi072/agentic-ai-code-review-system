from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    # Github webhook secret
    GITHUB_WEBHOOK_SECRET: str = ""

    model_config = SettingsConfigDict(env_prefix=".env", extra="ignore")

settings = Settings()