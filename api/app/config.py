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
    # HACK(demo): placeholder model ids; confirm the exact ids before M1 (override via .env).
    model_compile: str = "claude-sonnet-4-5"
    model_judge: str = "claude-sonnet-4-5"
    model_parse: str = "claude-haiku-4-5"
    model_closer: str = "claude-sonnet-4-5"

    # "off" runs the real pipeline; "replay" re-emits recorded runs from data/fixtures/runs.
    demo_mode: Literal["off", "replay"] = "off"

    database_url: str = f"sqlite:///{API_DIR / 'app.db'}"
    # ClinicalTrials.gov search radius around Sacramento (SPEC.md: 50 mi).
    ctgov_radius_mi: float = 50.0
    # `make seed` radius. HACK(demo): wider than the spec's 50 mi because only ~53 recruiting
    # T2D/CKD trials sit within 50 mi; 100 mi (adds the Bay Area) gives ~197. Set to 50 to revert.
    ctgov_seed_radius_mi: float = 100.0

    # Nearest cached trials a match run compiles and evaluates (SPEC.md: "about 20 trials").
    match_max_trials: int = 20

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # HACK(demo): stub — gap between the stub match's fake trace events (SPEC.md: 300 ms).
    stub_event_delay_s: float = 0.3

    # USD per million tokens, (input, output). Anthropic first-party list prices; a model id
    # matches an entry exactly or by prefix (dated ids like `claude-sonnet-4-5-20250929`).
    model_prices: dict[str, tuple[float, float]] = {
        "claude-sonnet-4-5": (3.0, 15.0),
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-sonnet-5": (2.0, 10.0),
        "claude-sonnet-5-5": (2.0, 10.0),
        "claude-haiku-4-5": (1.0, 5.0),
        "claude-haiku-5-5": (0.10, 0.50),
        "claude-opus-5-5": (4.0, 20.0),
    }

    def cost_usd(self, model: str | None, tokens_in: int, tokens_out: int) -> float | None:
        """Cost of one call, or None when the model isn't in the price table."""
        if not model:
            return None
        matches = [k for k in self.model_prices if model == k or model.startswith(f"{k}-")]
        if not matches:
            return None
        price_in, price_out = self.model_prices[max(matches, key=len)]
        return (tokens_in * price_in + tokens_out * price_out) / 1_000_000

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
