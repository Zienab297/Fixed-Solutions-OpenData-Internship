from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    KEYCLOAK_URL: str          # e.g. http://localhost:8080
    KEYCLOAK_REALM: str        # e.g. my-realm
    KEYCLOAK_CLIENT_ID: str
    KEYCLOAK_CLIENT_SECRET: str

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

settings = Settings()