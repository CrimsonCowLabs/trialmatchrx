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
