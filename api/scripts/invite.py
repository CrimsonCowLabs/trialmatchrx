"""Print a one-time invite link (SPEC.md "Marketing and accounts", Admin CLI).

    uv run python -m scripts.invite EMAIL [--base-url URL]

In prod, inside the API container (WORKDIR /app/api, no make):

    ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api \\
        python -m scripts.invite someone@example.com'

The link is `<base>/invite/<token>`; the base is APP_URL (settings `app_url`) unless
`--base-url` is given. It works once and expires after 7 days. There's no email sending: send
the link yourself. An email that already has an account is refused (exit 1); something that
isn't an email address is refused (exit 2). A refusal creates nothing.
"""

import argparse
import sys

from app.auth import invites
from app.auth.users import normalize_email
from app.config import get_settings
from app.db import init_db


def looks_like_email(email: str) -> bool:
    """Not a full address check: enough to catch a swapped, empty or mistyped argument."""
    local, at, domain = email.partition("@")
    return (
        bool(local and at and domain) and "@" not in domain and not any(c.isspace() for c in email)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("email")
    parser.add_argument("--base-url", help="the site's public origin (default: APP_URL)")
    args = parser.parse_args(argv)
    email = normalize_email(args.email)
    if not looks_like_email(email):
        print(f"refusing: {args.email!r} is not an email address", file=sys.stderr)
        return 2
    init_db()
    try:
        issued = invites.create(email)
    except invites.AlreadyHasAccount:
        print(f"refusing: {email} already has an account; nothing created", file=sys.stderr)
        return 1
    base = (args.base_url or get_settings().app_url).rstrip("/")
    expires = f"{issued.expires_at:%Y-%m-%d %H:%M} UTC"
    print(f"Invite for {email}: one use, expires in 7 days ({expires}). Send it yourself:")
    print(f"{base}/invite/{issued.token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
