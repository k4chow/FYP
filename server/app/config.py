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
    # Used only when llm_provider = "openai" (D33). The key must come from the
    # environment (.env locally, hosting env settings when deployed) and is
    # never committed or sent to the client.
    openai_api_key: str = ""
    openai_model: str = "gpt-6-luna"

    # Personalisation budgets and request-aware ranking weights (Parts A-D).
    # llm_context_mentioned_films caps how many other films one message may pull
    # into a reflection; llm_context_watched / _watchlist bound the viewing
    # history passed to discovery; recommendation_pool_size_chat is the chat
    # candidate pool the Film Assistant picks from; the weights below are the
    # conceptual scoring dimensions from the recommendation pipeline (defaults
    # keep prior behaviour until a request is stated).
    llm_context_mentioned_films: int = 3
    llm_context_watched: int = 15
    llm_context_watchlist: int = 10
    recommendation_pool_size_chat: int = 40
    recommendation_weights_mood: float = 0.20
    recommendation_weights_taste: float = 0.30
    recommendation_weights_reflection: float = 0.20
    recommendation_weights_experience: float = 0.15
    recommendation_weights_novelty: float = 0.15


settings = Settings()
