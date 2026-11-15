import asyncio

from app.trace.bus import EventBus
from tests.test_store import make_event


async def drain(sub: "asyncio.Queue[object]") -> list[object]:
    out = []
    while not sub.empty():
        out.append(sub.get_nowait())
    return out


async def test_subscriber_receives_published_events_then_done() -> None:
    bus = EventBus()
    async with bus.subscribe("r1") as sub:
        bus.publish(make_event("r1", 1, "a"))
        bus.publish(make_event("r1", 2, "b"))
        bus.close("r1")

        received = [await sub.get() for _ in range(3)]

    assert [getattr(e, "seq", e) for e in received] == [1, 2, EventBus.DONE]


async def test_every_subscriber_gets_every_event() -> None:
    bus = EventBus()
    async with bus.subscribe("r1") as a, bus.subscribe("r1") as b:
        bus.publish(make_event("r1", 1, "a"))
        assert [e.seq for e in await drain(a)] == [1]  # type: ignore[attr-defined]
        assert [e.seq for e in await drain(b)] == [1]  # type: ignore[attr-defined]


async def test_events_for_other_runs_are_not_delivered() -> None:
    bus = EventBus()
    async with bus.subscribe("r1") as sub:
        bus.publish(make_event("r2", 1, "a"))
        bus.close("r2")
        assert await drain(sub) == []


async def test_unsubscribe_on_exit() -> None:
    bus = EventBus()
    async with bus.subscribe("r1"):
        assert bus.subscriber_count("r1") == 1
    assert bus.subscriber_count("r1") == 0
    bus.publish(make_event("r1", 1, "a"))  # no subscribers: a no-op, not an error
