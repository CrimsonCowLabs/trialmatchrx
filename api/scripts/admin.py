"""Make an existing account an admin (SPEC.md "Admin"): the only way `users.is_admin` is set.

    uv run python -m scripts.admin EMAIL

In prod, inside the API container (WORKDIR /app/api, no make):

    ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api \\
        python -m scripts.admin EMAIL'

The email is matched normalized (trimmed, lowercased). An unknown email changes nothing and
exits 2. An account that's already an admin says so and exits 0. A disabled account can be made
an admin, but it still can't sign in. There is no command to take admin away.
"""

import argparse
import sys

from sqlmodel import select

from app.auth import users
from app.db import UserRow, init_db, session_scope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("email")
    email = users.normalize_email(parser.parse_args(argv).email)
    init_db()
    with session_scope() as s:
        row = s.exec(select(UserRow).where(UserRow.email == email)).first()
        if row is None:
            print(f"no account {email}", file=sys.stderr)
            return 2
        already = row.is_admin
        row.is_admin = True
        disabled = row.disabled_at is not None
    note = " (the account is disabled, so it still can't sign in)" if disabled else ""
    print(f"{email} is already an admin{note}" if already else f"made {email} an admin{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
