from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app import db
from app.config import get_settings
from app.main import app
from app.pipeline.fixture_model import FixtureChatModel, load_llm_fixture
from app.pipeline.judge import JudgeModelUnavailable
from app.routers.match import judge_model_factory, parse_model_factory
from app.routers.trials import compile_model_factory
from app.sources import ctgov

PARSE_FIXTURES = Path(__file__).parent / "fixtures" / "parse_patient"


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path) -> Iterator[None]:
    """Every test gets its own SQLite file."""
    db.set_engine(db.make_engine(f"sqlite:///{tmp_path / 'test.db'}"))
    db.init_db()
    yield
    db.get_engine().dispose()


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected network call: {request.method} {request.url}")


@pytest.fixture(autouse=True)
def no_ctgov_network(request: pytest.FixtureRequest) -> Iterator[None]:
    """ClinicalTrials.gov clients fail loudly on any request unless a test installs its own
    transport. Live tests (`-m live`) keep the real one."""
    if request.node.get_closest_marker("live") is None:
        ctgov.set_transport(httpx.MockTransport(_no_network))
    yield
    ctgov.set_transport(None)


@pytest.fixture(autouse=True)
def fixture_parse_model() -> Iterator[FixtureChatModel]:
    """Match runs parse the note with the saved demo-patient output, not Haiku."""
    model = FixtureChatModel(
        output=load_llm_fixture("demo_short", root=PARSE_FIXTURES),
        model_name=get_settings().model_parse,
    )
    app.dependency_overrides[parse_model_factory] = lambda: lambda: model
    yield model
    app.dependency_overrides.pop(parse_model_factory, None)


@pytest.fixture
def no_api_key() -> Iterator[None]:
    """No ANTHROPIC_API_KEY: a compile-cache miss (or any real model factory) must not reach
    Anthropic, because the real factories raise without a key."""
    app.dependency_overrides.pop(compile_model_factory, None)
    settings = get_settings()
    original, settings.anthropic_api_key = settings.anthropic_api_key, None
    yield
    settings.anthropic_api_key = original


def _no_judge_model() -> FixtureChatModel:
    raise JudgeModelUnavailable("tests: no judge model unless a test installs one")


@pytest.fixture(autouse=True)
def no_judge_model() -> Iterator[None]:
    """Match runs never reach the real judge: criteria without a rule stay `unknown` unless a
    test overrides `judge_model_factory` with a fixture model."""
    app.dependency_overrides[judge_model_factory] = lambda: _no_judge_model
    yield
    app.dependency_overrides.pop(judge_model_factory, None)
