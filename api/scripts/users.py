"""List every account: email, created date, last sign-in, passkeys, password set, disabled,
admin.

    uv run python -m scripts.users

In prod, inside the API container (WORKDIR /app/api, no make):

    ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api \\
        python -m scripts.users'

Oldest account first. Times are UTC. Read-only; always exits 0.
"""

import argparse
import datetime as dt

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.db import PasskeyRow, UserRow, as_utc, init_db, session_scope

HEADER = ("EMAIL", "CREATED", "LAST_SIGN_IN", "PASSKEYS", "PASSWORD", "DISABLED", "ADMIN")


def passkey_counts(s: Session) -> dict[str, int]:
    """How many passkeys each account has, by user id (accounts with none are missing)."""
    rows = s.exec(select(PasskeyRow.user_id, func.count()).group_by(col(PasskeyRow.user_id)))
    return {user_id: count for user_id, count in rows}


def _day(value: dt.datetime) -> str:
    return as_utc(value).strftime("%Y-%m-%d")


def _minute(value: dt.datetime) -> str:
    return as_utc(value).strftime("%Y-%m-%d %H:%M")


def display_rows() -> list[tuple[str, ...]]:
    """One display row per account, oldest first."""
    with session_scope() as s:
        counts = passkey_counts(s)
        accounts = s.exec(select(UserRow).order_by(col(UserRow.created_at), col(UserRow.email)))
        return [
            (
                u.email,
                _day(u.created_at),
                _minute(u.last_login_at) if u.last_login_at else "never",
                str(counts.get(u.id, 0)),
                "yes" if u.password_hash else "no",
                _day(u.disabled_at) if u.disabled_at else "no",
                "yes" if u.is_admin else "no",
            )
            for u in accounts
        ]


def format_table(table: list[tuple[str, ...]]) -> str:
    widths = [max(len(cell) for cell in column) for column in zip(*table, strict=True)]
    return "\n".join(
        "  ".join(cell.ljust(w) for cell, w in zip(line, widths, strict=True)).rstrip()
        for line in table
    )


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args(argv)
    init_db()
    accounts = display_rows()
    print(format_table([HEADER, *accounts]) if accounts else "no accounts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
