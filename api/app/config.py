"""Settings from the environment / `.env` (pydantic-settings)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
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
    # Where `scripts/record_demo.py` writes the run fixtures replay mode reads (SPEC.md).
    demo_fixtures_dir: Path = REPO_DIR / "data" / "fixtures" / "runs"
    # Longest wait between two replayed emissions; recorded gaps above it are cut (SPEC.md).
    demo_replay_max_gap_s: float = 0.2

    database_url: str = f"sqlite:///{API_DIR / 'app.db'}"
    # ClinicalTrials.gov search radius around Sacramento (SPEC.md: 50 mi).
    ctgov_radius_mi: float = 50.0
    # `make seed` radius. HACK(demo): wider than the spec's 50 mi because only ~53 recruiting
    # T2D/CKD trials sit within 50 mi; 100 mi (adds the Bay Area) gives ~197. Set to 50 to revert.
    # The match search default (schemas.MatchRequest.radius_mi, web DEFAULT_RADIUS_MI) is this
    # same 100 mi; keep them in step.
    ctgov_seed_radius_mi: float = 100.0

    # Nearest cached trials a match run compiles and evaluates (SPEC.md: "about 20 trials").
    match_max_trials: int = 20

    # Share of criteria the compiler should turn into predicates (SPEC.md: "about 60%"); the
    # /eval page shows the measured compile rate against it.
    eval_compile_rate_target: float = Field(default=0.6, ge=0, le=1)

    # Explicit origins only: requests carry the session cookie (allow_credentials).
    cors_origins: list[str] = ["http://localhost:3045", "http://127.0.0.1:3045"]

    # The session cookie's Secure flag. On unless turned off: `make dev` / `make api` set
    # SESSION_COOKIE_SECURE=false, since the dev API is plain http://localhost.
    session_cookie_secure: bool = True
    # The site's public origin, for the links the admin CLI prints (`make invite`, `make
    # reset-link`). compose.yaml sets the prod one.
    app_url: str = "http://localhost:3045"
    # Proxies (CIDR) whose X-Forwarded-For the sign-in throttle believes (app/auth/client_ip.py).
    # compose.yaml adds the Docker bridge ranges: Caddy's requests reach the container from the
    # bridge gateway, not from 127.0.0.1.
    trusted_proxies: list[str] = ["127.0.0.0/8", "::1/128"]

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

    @field_validator("cors_origins")
    @classmethod
    def _explicit_origins(cls, origins: list[str]) -> list[str]:
        if "*" in origins:
            raise ValueError(
                "CORS_ORIGINS must list explicit origins, not *: requests carry the session cookie"
            )
        return origins

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
