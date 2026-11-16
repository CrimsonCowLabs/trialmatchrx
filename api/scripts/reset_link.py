"""Print a one-time password-reset link for an account (SPEC.md "Marketing and accounts").

    uv run python -m scripts.reset_link EMAIL

In prod, inside the API container (WORKDIR /app/api, no make):

    ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api \\
        python -m scripts.reset_link someone@example.com'

There's no email sending: send the printed link yourself. It works once, for 1 hour, and sets a
new password at `/reset/<token>`, which also ends all of that account's sessions. The link's
origin is `APP_URL` (app/config.py `app_url`). A refusal (no account with that email, or the
account is disabled) prints why, makes no link and exits 2.
"""

import argparse
import sys

from app.auth import resets, users
from app.config import get_settings
from app.db import init_db


def reset_url(token: str) -> str:
    return f"{get_settings().app_url.rstrip('/')}/reset/{token}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("email", help="the account's email")
    args = parser.parse_args(argv)

    init_db()
    user = users.find_by_email(args.email)
    if user is None:
        print(f"reset-link: no account for {args.email!r}", file=sys.stderr)
        return 2
    try:
        token = resets.create(user.id)
    except resets.ResetRefused:
        print(f"reset-link: {user.email} is disabled; no link made", file=sys.stderr)
        return 2
    hours = int(resets.RESET_TTL.total_seconds() // 3600)
    print(f"Password-reset link for {user.email} (one use, expires in {hours} hour):")
    print(reset_url(token))
    return 0


if __name__ == "__main__":
    sys.exit(main())
