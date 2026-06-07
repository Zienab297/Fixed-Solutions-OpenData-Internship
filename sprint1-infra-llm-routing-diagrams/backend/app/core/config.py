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

    LOCAL_LLM_BASE_URL: str = "https://your-colab-tunnel-url/v1"
    LOCAL_LLM_MODEL: str = "Qwen/Qwen3-8B"
    LOCAL_LLM_QUANTIZATION: str = "4-bit"
    LOCAL_LLM_HOSTING: str = "google-colab"
    JUDGE_MODEL: str = "Qwen/Qwen3-8B"
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-large"

    GEMINI_API_KEY: str = ""
    API_LLM_PROVIDER: str = "gemini"
    API_LLM_MODEL: str = "gemini-3.5-flash"

    MOCK_LLM_RESPONSES: bool = True

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()
