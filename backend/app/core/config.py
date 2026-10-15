from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./legal.db"
    groq_api_key: str | None = None
    llm_model: str = "openai/gpt-oss-120b"
    llm_timeout_s: int = 60
    embedding_backend: str = "fastembed"   # "fastembed" (bge-small) | "hash" (offline/tests)
    reranker: str = "cross-encoder"        # "cross-encoder" | "none"
    cors_origins: list[str] = ["http://localhost:5173"]
    max_upload_mb: int = 15
    chunk_target_chars: int = 900
    chunk_overlap_chars: int = 120
    top_k: int = 5                         # chunks that reach the LLM
    secret_key: str = "change-me-in-production"
    access_token_minutes: int = 60
    refresh_token_days: int = 7
    data_dir: str = "./data"               # uploaded originals live here so ingestion can resume after a restart
    log_json: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
