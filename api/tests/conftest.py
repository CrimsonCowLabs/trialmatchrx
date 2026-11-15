from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app import db
from app.sources import ctgov


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
