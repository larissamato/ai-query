from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, HttpUrl, SecretStr, StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    ai_query_password: SecretStr = Field(min_length=1)
    ai_query_db_host: str = "postgres"
    ai_query_db_port: int = Field(default=5432, ge=1, le=65535)
    ollama_base_url: HttpUrl = HttpUrl("http://ollama:11434")
    ollama_model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = (
        "qwen2.5:3b"
    )
    ollama_timeout_seconds: float = Field(default=120, gt=0, le=600)


@lru_cache
def get_settings() -> Settings:
    return Settings()
