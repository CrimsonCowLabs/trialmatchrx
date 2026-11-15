from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app import db
from app.config import get_settings
from app.main import app
from app.pipeline.fixture_model import FixtureChatModel, load_llm_fixture
from app.routers.match import parse_model_factory
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
        tool_name="DraftPatient",
        model_name=get_settings().model_parse,
    )
    app.dependency_overrides[parse_model_factory] = lambda: lambda: model
    yield model
    app.dependency_overrides.pop(parse_model_factory, None)
