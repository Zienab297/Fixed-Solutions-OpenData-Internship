from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    APP_SECRET_KEY: str = "change-me"

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

    # His generic aliases — kept so his services don't break
    AUTH_PROVIDER_URL: str = ""
    METADATA_STORE_URL: str = ""
    VECTOR_STORE_URL: str = ""
    GRAPH_STORE_URL: str = ""
    QUEUE_URL: str = ""

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

    # Local LLM — his Colab/Qwen setup
    LOCAL_LLM_BASE_URL: str = "https://your-colab-tunnel-url/v1"
    LOCAL_LLM_MODEL: str = "Qwen/Qwen3-8B"
    LOCAL_LLM_QUANTIZATION: str = "4-bit"
    LOCAL_LLM_HOSTING: str = "google-colab"

    # Ollama base URL (your setup)
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Embedding + generation — bge-m3 via Ollama
    EMBEDDING_MODEL: str = "bge-m3:latest"
    GENERATION_MODEL: str = "bge-m3:latest"
    JUDGE_MODEL: str = "bge-m3:latest"

    # External LLM — his Gemini setup
    GEMINI_API_KEY: str = ""
    API_LLM_PROVIDER: str = "gemini"
    API_LLM_MODEL: str = "gemini-3.5-flash"

    # Mock flag — useful for testing without a running LLM
    MOCK_LLM_RESPONSES: bool = True

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # Supported languages
    SUPPORTED_LANGUAGES: List[str] = ["en", "ar", "fr", "de", "es"]

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()