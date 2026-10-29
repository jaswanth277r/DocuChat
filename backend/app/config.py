from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", BASE_DIR / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "DocuChat"
    environment: str = "development"
    api_prefix: str = "/api"

    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_ttl_hours: int = 72
    cookie_name: str = "docuchat_session"
    cookie_secure: bool = False

    mongo_url: str = "mongodb://127.0.0.1:27017"
    mongo_db: str = "docuchat"
    redis_url: str = "redis://127.0.0.1:6379/0"

    data_dir: Path = BASE_DIR / "data"
    max_upload_mb: int = 25
    max_pages: int = 500
    retention_days: int = 30

    embed_provider: str = "fastembed"  # fastembed | hashing | openai
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache_dir: str = str(BASE_DIR / "data" / "models")
    embed_batch_size: int = 32

    llm_provider: str = "extractive"  # extractive | openai | ollama
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1200
    llm_timeout_s: int = 90

    retrieval_top_k: int = 20
    rerank_top_n: int = 5
    rrf_k: int = 60
    vector_weight: float = 0.7
    bm25_weight: float = 0.3
    enable_rerank: bool = True
    enable_support_verification: bool = True
    min_retrieval_confidence: float = 0.22
    max_context_tokens: int = 5000

    uploads_per_hour: int = 10
    chats_per_hour: int = 120

    serve_frontend: bool = True

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "extractive":
            return True
        if self.llm_provider in {"openai", "groq"}:
            return bool(self.llm_api_key)
        if self.llm_provider == "ollama":
            return bool(self.llm_base_url)
        return False


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.data_dir.is_absolute():
        settings.data_dir = (BASE_DIR / settings.data_dir).resolve()
    cache_dir = Path(settings.embed_cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = (BASE_DIR / cache_dir).resolve()
        settings.embed_cache_dir = str(cache_dir)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return settings
