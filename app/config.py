"""Pydantic BaseSettings configuration loaded from .env (OPENAI_API_KEY, DB paths, model names, cache config)."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = Field(repr=False, validation_alias="OPENAI_API_KEY")
    model_name: str = Field("gpt-5-mini", validation_alias=AliasChoices("MODEL_NAME", "model_name"))
    embedding_model: str = Field(
        "text-embedding-3-small",
        validation_alias=AliasChoices("EMBEDDING_MODEL", "embedding_model"),
    )
    db_path: str = Field("data/actuators.db", validation_alias=AliasChoices("SQLITE_DB_PATH", "db_path"))
    memory_db_path: str = Field(
        "data/memory.db",
        validation_alias=AliasChoices("MEMORY_DB_PATH", "memory_db_path"),
    )
    chroma_path: str = Field("data/chroma", validation_alias=AliasChoices("CHROMA_PATH", "chroma_path"))
    rate_limit: str = Field("30/minute", validation_alias=AliasChoices("RATE_LIMIT", "rate_limit"))
    cache_ttl: int = 3600
    cache_max_size: int = 500
    log_level: str = "INFO"


settings = Settings()
