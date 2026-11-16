"""Per-model price table."""

import pytest

from app.config import Settings


def test_cost_for_exact_and_dated_model_ids() -> None:
    s = Settings()
    assert s.cost_usd("claude-haiku-4-5", 1_000_000, 0) == pytest.approx(1.0)
    assert s.cost_usd("claude-sonnet-4-5-20250929", 0, 1_000_000) == pytest.approx(15.0)


def test_cost_for_unknown_model_is_none() -> None:
    assert Settings().cost_usd("GenericFakeChatModel", 10, 10) is None
    assert Settings().cost_usd(None, 10, 10) is None


def test_cors_origins_must_be_explicit() -> None:
    # Requests carry the session cookie (allow_credentials), and with "*" Starlette echoes any
    # origin back, which would let any site make credentialed calls past the CSRF guard.
    with pytest.raises(ValueError, match="explicit"):
        Settings(cors_origins=["*"])
    assert Settings(cors_origins=["http://localhost:3245"]).cors_origins == [
        "http://localhost:3245"
    ]
