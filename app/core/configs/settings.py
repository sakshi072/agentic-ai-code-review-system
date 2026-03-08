from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    # Github webhook secret
    GITHUB_WEBHOOK_SECRET: str = ""
    GITHUB_TOKEN:str=""
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    # Default Agent LLM 
    DEFAULT_AGENT_MODEL_ID:str = "deepseek-coder-v2"
    DEFAULT_AGENT_TEMPERATURE:float = 0
    DEFAULT_AGENT_BASE_URL:str="http://localhost:11434"

settings = Settings()