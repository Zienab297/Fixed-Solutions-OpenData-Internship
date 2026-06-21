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

    # Local embeddings
    EMBEDDING_MODEL: str = "bge-m3:latest"
    EMBEDDING_DIMENSION: int = 1024

    # Ollama — local generation
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Local LLM (Ollama OpenAI-compatible endpoint)
    LOCAL_LLM_MODEL: str = "qwen3:8b"
    LOCAL_LLM_BASE_URL: str = "http://localhost:11434/v1"
    LOCAL_LLM_TIMEOUT_SECONDS: float = 240.0
    LOCAL_LLM_MAX_TOKENS: int = 2048
    LOCAL_LLM_CONTEXT_CHUNKS: int = 3
    LOCAL_LLM_CHUNK_CHARS: int = 1200
    LOCAL_LLM_CONTEXT_CHARS: int = 4200

    # External LLM (Gemini)
    GEMINI_API_KEY: Optional[str] = None
    API_LLM_MODEL: str = "gemini-1.5-flash"

    # Legacy alias kept for any code that still reads GENERATION_MODEL
    GENERATION_MODEL: str = "qwen3:8b"

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # Set to True to return mock LLM responses without hitting Ollama/Gemini
    MOCK_LLM_RESPONSES: bool = False

    # Dev mode disabled — using local JWT auth instead of Keycloak
    DEV_MODE: bool = False

    # Secret key for signing local JWTs (change in production)
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours

    # System admin seeded on first run
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = "changeme123"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

settings = Settings()