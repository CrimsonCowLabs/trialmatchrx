"""Disable an account: end all its sessions and block sign-in by any method. The row stays,
so a run's `created_by` still resolves.

    uv run python -m scripts.disable_user EMAIL

In prod, inside the API container (WORKDIR /app/api, no make):

    ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api \\
        python -m scripts.disable_user EMAIL'

The email is matched normalized (trimmed, lowercased). An unknown email changes nothing and
exits 2. Disabling an already-disabled account says so, keeps its first disabled date, still
ends any sessions it has, and exits 0. There is no re-enable command.
"""

import argparse
import sys

from app.auth import sessions, users
from app.db import UserRow, as_utc, init_db, session_scope, utcnow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("email")
    email = users.normalize_email(parser.parse_args(argv).email)
    init_db()
    found = users.find_by_email(email)
    if found is None:
        print(f"no account {email}", file=sys.stderr)
        return 2
    with session_scope() as s:
        row = s.get(UserRow, found.id)
        assert row is not None
        already = row.disabled_at
        if already is None:
            row.disabled_at = utcnow()
        ended = sessions.end_user_sessions(s, row.id)
    if already is not None:
        since = as_utc(already).strftime("%Y-%m-%d %H:%M UTC")
        print(f"{email} is already disabled (since {since}); {ended} sessions ended")
    else:
        print(f"disabled {email}; {ended} sessions ended")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
