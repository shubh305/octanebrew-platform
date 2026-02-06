from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    REDIS_URL: str = "redis://redis:6379/0"
    SERVICE_NAME: str = "dictionary-service"
    APP_TITLE: str = "Dictionary Service"
    SERVICE_API_KEY: str = ""
    
    class Config:
        env_file = ".env"

settings = Settings()
