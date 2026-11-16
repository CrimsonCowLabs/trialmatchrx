"""app/auth/client_ip.py: the IP the throttle counts. X-Forwarded-For is believed only when the
connection comes from a trusted proxy (Caddy), and then only its last hop, the one Caddy added."""

from app.auth.client_ip import client_ip

LOOPBACK = ["127.0.0.0/8", "::1/128"]
WITH_DOCKER = [*LOOPBACK, "172.16.0.0/12"]


def test_a_direct_connection_is_its_own_ip_whatever_it_claims() -> None:
    assert client_ip("203.0.113.7", "198.51.100.1", LOOPBACK) == "203.0.113.7"
    assert client_ip("203.0.113.7", None, LOOPBACK) == "203.0.113.7"


def test_behind_a_trusted_proxy_the_last_forwarded_hop_is_the_client() -> None:
    assert client_ip("127.0.0.1", "198.51.100.1", LOOPBACK) == "198.51.100.1"
    # A client can prepend anything; only the hop the proxy appended counts.
    assert client_ip("127.0.0.1", "10.9.9.9, 198.51.100.1", LOOPBACK) == "198.51.100.1"
    assert client_ip("::1", " 2001:db8::5 ", LOOPBACK) == "2001:db8::5"


def test_the_docker_bridge_gateway_can_be_trusted_by_setting() -> None:
    assert client_ip("172.18.0.1", "198.51.100.1", WITH_DOCKER) == "198.51.100.1"
    assert client_ip("172.18.0.1", "198.51.100.1", LOOPBACK) == "172.18.0.1"


def test_a_trusted_proxy_without_a_usable_header_is_the_peer() -> None:
    assert client_ip("127.0.0.1", None, LOOPBACK) == "127.0.0.1"
    assert client_ip("127.0.0.1", "", LOOPBACK) == "127.0.0.1"
    assert client_ip("127.0.0.1", "not-an-ip", LOOPBACK) == "127.0.0.1"


def test_no_peer_at_all_is_unknown() -> None:
    assert client_ip(None, "198.51.100.1", LOOPBACK) == "unknown"
