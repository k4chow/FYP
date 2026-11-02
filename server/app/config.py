from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    tmdb_api_key: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
