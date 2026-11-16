"""app/auth/throttle.py: 5 failed sign-ins in 15 minutes for the same email OR the same IP
throttle further attempts; nothing ever locks for good."""

import datetime as dt

from app.auth import throttle

T0 = dt.datetime(2026, 11, 16, 12, 0, tzinfo=dt.UTC)


def fail(n: int, email: str, ip: str, at: dt.datetime = T0) -> None:
    for i in range(n):
        throttle.record_failure(email, ip, now=at + dt.timedelta(seconds=i))


def test_four_failures_are_not_throttled_and_the_fifth_is() -> None:
    fail(4, "ana@example.com", "203.0.113.1")
    assert not throttle.is_throttled(
        "ana@example.com", "203.0.113.1", now=T0 + dt.timedelta(seconds=10)
    )
    fail(1, "ana@example.com", "203.0.113.1")
    assert throttle.is_throttled("ana@example.com", "203.0.113.1", now=T0 + dt.timedelta(minutes=1))


def test_the_same_email_from_other_ips_is_throttled() -> None:
    for i in range(5):
        throttle.record_failure("ana@example.com", f"203.0.113.{i}", now=T0)
    assert throttle.is_throttled("ana@example.com", "198.51.100.9", now=T0)
    assert not throttle.is_throttled("bo@example.com", "198.51.100.9", now=T0)


def test_the_same_ip_with_other_emails_is_throttled() -> None:
    for i in range(5):
        throttle.record_failure(f"user{i}@example.com", "203.0.113.1", now=T0)
    assert throttle.is_throttled("new@example.com", "203.0.113.1", now=T0)
    assert not throttle.is_throttled("new@example.com", "203.0.113.2", now=T0)


def test_email_matching_ignores_case_and_spaces() -> None:
    for i in range(5):
        throttle.record_failure(" Ana@Example.com", f"203.0.113.{i}", now=T0)
    assert throttle.is_throttled("ana@example.com", "198.51.100.9", now=T0)


def test_failures_older_than_15_minutes_stop_counting() -> None:
    fail(5, "ana@example.com", "203.0.113.1")  # T0 .. T0+4s
    assert throttle.is_throttled(
        "ana@example.com", "203.0.113.1", now=T0 + dt.timedelta(minutes=14)
    )
    assert not throttle.is_throttled(
        "ana@example.com", "203.0.113.1", now=T0 + dt.timedelta(minutes=15, seconds=1)
    )
