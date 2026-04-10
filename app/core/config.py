import os
from pydantic_settings import BaseSettings

# Ensure the data directory exists for SQLite persistence
os.makedirs("data", exist_ok=True)

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/sqlite.db"
    DEBUG: bool = True
    CORS_ORIGINS: list[str] = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()