from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "change-me"
    APP_PORT: int = 8000

    # PostgreSQL
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "ragdb"
    POSTGRES_USER: str = "raguser"
    POSTGRES_PASSWORD: str = "ragpassword"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:"
            f"{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:"
            f"{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}"

    # Keycloak
    KEYCLOAK_URL: str = "http://localhost:8080"
    KEYCLOAK_REALM: str = "rag-system"
    KEYCLOAK_CLIENT_ID: str = "rag-backend"
    KEYCLOAK_CLIENT_SECRET: str = "change-me"

    # Ollama (local LLM)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    GENERATION_MODEL: str = "llama3"
    JUDGE_MODEL: str = "llama3"
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-large"

    # External LLM API
    EXTERNAL_LLM_API_KEY: str = ""
    EXTERNAL_LLM_MODEL: str = "claude-sonnet-4-20250514"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Supported languages for MVP
    SUPPORTED_LANGUAGES: List[str] = ["en", "ar", "fr", "de", "es"]

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
