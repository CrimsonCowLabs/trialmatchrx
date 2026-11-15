from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path) -> Iterator[None]:
    """Every test gets its own SQLite file."""
    db.set_engine(db.make_engine(f"sqlite:///{tmp_path / 'test.db'}"))
    db.init_db()
    yield
    db.get_engine().dispose()
