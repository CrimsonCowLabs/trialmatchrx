"""Settings from the environment / `.env` (pydantic-settings)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = API_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", API_DIR / ".env"), extra="ignore"
    )

    anthropic_api_key: str | None = None
    model_compile: str = "claude-sonnet-4-5"
    model_judge: str = "claude-sonnet-4-5"
    model_parse: str = "claude-haiku-4-5"
    model_closer: str = "claude-sonnet-4-5"

    # "off" runs the real pipeline; "replay" re-emits recorded runs from data/fixtures/runs.
    demo_mode: Literal["off", "replay"] = "off"

    database_url: str = f"sqlite:///{API_DIR / 'app.db'}"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # HACK(demo): stub — gap between the stub match's fake trace events (SPEC.md: 300 ms).
    stub_event_delay_s: float = 0.3

    def model_ids(self) -> dict[str, str]:
        return {
            "compile": self.model_compile,
            "judge": self.model_judge,
            "parse": self.model_parse,
            "closer": self.model_closer,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
