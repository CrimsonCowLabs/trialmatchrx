"""Tiny SSE parser and ASGI client helpers for tests."""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.main import app


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


def client() -> httpx.AsyncClient:
    """The app's client: sends X-Requested-With like web/lib/api.ts, so POSTs pass the CSRF
    guard."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "fetch"},
    )
