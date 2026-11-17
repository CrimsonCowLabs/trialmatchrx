"""List request-access submissions, newest first: received, name, email, organization, role,
status (pending, invited or dismissed; SPEC.md "Admin"), and the message (if any) on the line
below.

    uv run python -m scripts.access_requests

In prod, inside the API container (WORKDIR /app/api, no make):

    ssh aaron@ccl-vps 'cd /app/trialmatchrx && docker compose -f compose.yaml exec -T api \\
        python -m scripts.access_requests'

Times are UTC. Read-only; always exits 0.
"""

import argparse

from sqlmodel import col, select

from app.db import AccessRequestRow, as_utc, init_db, session_scope
from scripts.users import format_table

HEADER = ("RECEIVED", "NAME", "EMAIL", "ORGANIZATION", "ROLE", "STATUS")


def display_rows() -> list[tuple[tuple[str, ...], str | None]]:
    """Each request's table cells and its message (on one line), newest first."""
    with session_scope() as s:
        query = select(AccessRequestRow).order_by(
            col(AccessRequestRow.created_at).desc(), col(AccessRequestRow.id).desc()
        )
        return [
            (
                (
                    as_utc(r.created_at).strftime("%Y-%m-%d %H:%M"),
                    r.name,
                    r.email,
                    r.organization,
                    r.role,
                    r.status,
                ),
                " ".join(r.message.split()) if r.message else None,
            )
            for r in s.exec(query)
        ]


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args(argv)
    init_db()
    rows = display_rows()
    if not rows:
        print("no access requests")
        return 0
    header, *lines = format_table([HEADER, *(cells for cells, _ in rows)]).splitlines()
    print(header)
    for line, (_, message) in zip(lines, rows, strict=True):
        print(line)
        if message:
            print(f"    {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
