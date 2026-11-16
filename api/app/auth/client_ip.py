"""The client IP the sign-in throttle counts.

In prod uvicorn sits behind the box's host-networked Caddy, which reaches the container through
its loopback-published port. Caddy sets X-Forwarded-For to the address it saw (it ignores an
incoming X-Forwarded-For unless it was told to trust the sender), so the header's last entry is
the real client. The header is believed only when the TCP peer is in `Settings.trusted_proxies`;
from anyone else it's ignored, or a client could pick a fresh IP per attempt.

Uvicorn's own proxy-header handling (on by default, trusting 127.0.0.1 only) may already have
replaced `request.client` with the forwarded address when the peer is loopback; that address
isn't a trusted proxy, so it's used as is. In the container the peer is the bridge gateway,
which uvicorn doesn't trust, so this function is what reads the header there.
"""

import ipaddress
from collections.abc import Sequence
from functools import lru_cache

from fastapi import Request

from app.config import get_settings


@lru_cache(maxsize=8)
def _networks(
    trusted: tuple[str, ...],
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(n, strict=False) for n in trusted)


def _parse(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def client_ip(peer: str | None, forwarded_for: str | None, trusted: Sequence[str]) -> str:
    """`peer` is the TCP peer, `forwarded_for` the raw X-Forwarded-For header, `trusted` the
    proxy networks (CIDR) allowed to set it."""
    if peer is None:
        return "unknown"
    peer_ip = _parse(peer)
    if peer_ip is None or not any(peer_ip in n for n in _networks(tuple(trusted))):
        return peer
    last_hop = _parse((forwarded_for or "").split(",")[-1])
    return str(last_hop) if last_hop is not None else peer


def request_ip(request: Request) -> str:
    return client_ip(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        get_settings().trusted_proxies,
    )
