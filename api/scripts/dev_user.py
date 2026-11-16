"""Create (or reset) the local dev account, so `make dev` can be signed into.

    uv run python -m scripts.dev_user

Prints the email and password. Running it again keeps the one account and puts it back to the
known password, enabled. It refuses (exit 2, nothing changed) unless the database is the local
dev one: a SQLite file inside the repo's api/ directory, like the default api/app.db. The prod
container's database is /data/app.db, so it never runs there.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

from app.auth import passwords, users
from app.config import API_DIR
from app.db import UserRow, get_engine, init_db, session_scope

# HACK(demo): a fixed, printed dev credential. Only ever written to a database inside api/.
DEV_EMAIL = "dev@localhost"
DEV_PASSWORD = "trialmatch-local-dev"


def is_local_dev_db(url: str, api_dir: Path) -> bool:
    """Whether `url` is a SQLite file inside `api_dir` (path resolved, so `..` can't escape)."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database:
        return False
    if parsed.database == ":memory:":
        return False
    path = Path(parsed.database).resolve()
    return path.is_relative_to(api_dir.resolve())


def ensure_dev_user() -> None:
    """The dev account with the known password, enabled; created if missing."""
    problem = passwords.password_problem(DEV_PASSWORD)
    assert problem is None, problem
    hashed = passwords.hash_password(DEV_PASSWORD)
    existing = users.find_by_email(DEV_EMAIL)
    if existing is None:
        users.create_user(DEV_EMAIL, password_hash=hashed)
        return
    with session_scope() as s:
        row = s.get(UserRow, existing.id)
        assert row is not None
        row.password_hash = hashed
        row.disabled_at = None


def main(argv: list[str] | None = None, *, api_dir: Path = API_DIR) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args(argv)
    url = get_engine().url.render_as_string(hide_password=True)
    if not is_local_dev_db(url, api_dir):
        print(
            f"refusing: {url} is not the local dev database (a SQLite file inside {api_dir})",
            file=sys.stderr,
        )
        return 2
    init_db()
    ensure_dev_user()
    print(f"dev account ready: {DEV_EMAIL} / {DEV_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
