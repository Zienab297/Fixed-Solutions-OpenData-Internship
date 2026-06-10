from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    KEYCLOAK_URL: str = "http://localhost:8080"
    KEYCLOAK_REALM: str = "rag"
    KEYCLOAK_CLIENT_ID: str = "rag-api"
    KEYCLOAK_CLIENT_SECRET: str = "secret"

    CELERY_BROKER_URL: str = "redis://:changeme@localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://:changeme@localhost:6379/1"

    # Ollama — embedding + local generation
    EMBEDDING_MODEL: str = "bge-m3:latest"
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Local LLM (Ollama OpenAI-compatible endpoint)
    LOCAL_LLM_MODEL: str = "llama3.2:3b"
    LOCAL_LLM_BASE_URL: str = "http://localhost:11434/v1"

    # External LLM (Gemini)
    GEMINI_API_KEY: Optional[str] = None
    API_LLM_MODEL: str = "gemini-1.5-flash"

    # Legacy alias kept for any code that still reads GENERATION_MODEL
    GENERATION_MODEL: str = "llama3.2:3b"

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # Set to True to return mock LLM responses without hitting Ollama/Gemini
    MOCK_LLM_RESPONSES: bool = False

    # Set to "true" to skip Keycloak entirely (dev/demo mode)
    DEV_MODE: bool = True
    DEV_USER_ID: str = "dev-user-001"
    DEV_USER_EMAIL: str = "dev@example.com"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

settings = Settings()
