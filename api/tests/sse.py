"""Tiny SSE parser and ASGI client helpers for tests."""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.auth import sessions, users
from app.auth.deps import SESSION_COOKIE
from app.main import app

TEST_EMAIL = "tester@example.com"


@dataclass
class SSEMessage:
    event: str
    data: Any
    id: str | None


def parse_sse(body: str) -> list[SSEMessage]:
    messages = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            key, _, value = line.partition(":")
            fields[key] = fields.get(key, "") + value.removeprefix(" ")
        if "data" in fields:
            messages.append(
                SSEMessage(
                    fields.get("event", "message"), json.loads(fields["data"]), fields.get("id")
                )
            )
    return messages


def signed_in_user_id() -> str:
    """The account `client()` signs in as (created in this test's database on first use)."""
    user = users.find_by_email(TEST_EMAIL) or users.create_user(TEST_EMAIL, password_hash=None)
    return user.id


def client(*, signed_in: bool = True) -> httpx.AsyncClient:
    """The app's client: sends X-Requested-With like web/lib/api.ts, so POSTs pass the CSRF
    guard, and (unless `signed_in=False`) a session cookie for `TEST_EMAIL`, since every route
    but the public ones needs one (SPEC.md "Enforcement")."""
    cookies = {SESSION_COOKIE: sessions.create(signed_in_user_id())} if signed_in else None
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
        cookies=cookies,
    )
