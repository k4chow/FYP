from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    tmdb_api_key: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]

    # LLM provider seam (F5/D5): "mock" = deterministic, no API key needed.
    llm_provider: str = "mock"
    # Bounded context assembly (F4): last N messages + K confirmed memories.
    llm_context_messages: int = 12
    llm_context_memories: int = 5


settings = Settings()
