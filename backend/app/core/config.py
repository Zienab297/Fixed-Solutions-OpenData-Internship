from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    APP_SECRET_KEY: str = "change-me"

    AUTH_PROVIDER_URL: str = ""
    METADATA_STORE_URL: str = ""
    VECTOR_STORE_URL: str = ""
    GRAPH_STORE_URL: str = ""
    QUEUE_URL: str = ""

    DATABASE_URL: str = "sqlite:///./rag.db"
    KEYCLOAK_URL: str = "http://localhost:8080"
    KEYCLOAK_REALM: str = "rag-realm"
    KEYCLOAK_CLIENT_ID: str = "rag-backend"
    KEYCLOAK_CLIENT_SECRET: str = "change-me"
    FRONTEND_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    LOCAL_LLM_BASE_URL: str = "https://your-colab-tunnel-url/v1"
    LOCAL_LLM_MODEL: str = "Qwen/Qwen3-8B"
    LOCAL_LLM_QUANTIZATION: str = "4-bit"
    LOCAL_LLM_HOSTING: str = "google-colab"
    JUDGE_MODEL: str = "Qwen/Qwen3-8B"
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"

    GEMINI_API_KEY: str = ""
    API_LLM_PROVIDER: str = "gemini"
    API_LLM_MODEL: str = "gemini-3.5-flash"

    MOCK_LLM_RESPONSES: bool = True

    UPLOAD_DIR: str = "local_data/uploads"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "rag_chunks"
    INGESTION_CHUNK_SIZE: int = 2000
    INGESTION_CHUNK_OVERLAP: int = 200
    EMBEDDING_BATCH_SIZE: int = 32

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()
