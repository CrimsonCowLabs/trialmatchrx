"""List every account: email, created date, last sign-in, passkeys, password set, disabled.

    uv run python -m scripts.users

In prod, inside the API container (WORKDIR /app/api, no make):

    ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api \\
        python -m scripts.users'

Oldest account first. Times are UTC. Read-only; always exits 0.
"""

import argparse
import datetime as dt

from sqlmodel import col, select

from app.db import UserRow, as_utc, init_db, session_scope

HEADER = ("EMAIL", "CREATED", "LAST_SIGN_IN", "PASSKEYS", "PASSWORD", "DISABLED")


def passkey_count(user_id: str) -> int:
    """How many passkeys the account has."""
    # HACK(demo): passkeys (#4) aren't built yet and there is no passkeys table, so every
    # account has 0. #4 wires the real count here.
    return 0


def _day(value: dt.datetime) -> str:
    return as_utc(value).strftime("%Y-%m-%d")


def _minute(value: dt.datetime) -> str:
    return as_utc(value).strftime("%Y-%m-%d %H:%M")


def rows() -> list[tuple[str, ...]]:
    """One display row per account, oldest first."""
    with session_scope() as s:
        accounts = s.exec(select(UserRow).order_by(col(UserRow.created_at), col(UserRow.email)))
        return [
            (
                u.email,
                _day(u.created_at),
                _minute(u.last_login_at) if u.last_login_at else "never",
                str(passkey_count(u.id)),
                "yes" if u.password_hash else "no",
                _day(u.disabled_at) if u.disabled_at else "no",
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
    accounts = rows()
    print(format_table([HEADER, *accounts]) if accounts else "no accounts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
