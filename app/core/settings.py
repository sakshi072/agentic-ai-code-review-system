from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    # Github webhook secret
    GITHUB_WEBHOOK_SECRET: str = ""
    GITHUB_TOKEN:str=""
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

settings = Settings()