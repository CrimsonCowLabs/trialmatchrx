"""SPEC.md "Marketing and accounts", Enforcement: every `/api` route needs a session except
`GET /api/health`, `/api/auth/*` and `POST /api/access-requests`; `/api/admin/*` answers 404,
not 401, to anyone but an admin, signed out included.

The enumeration test walks every route registered on the app and calls it signed out, so a
route added later is covered without anyone remembering to add it here."""

import re

import pytest
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from starlette.routing import Mount, Route

from app.auth.deps import is_admin_path, is_public
from app.main import app
from app.trace import store
from tests.sse import client, parse_sse


def _routes() -> list[RouteContext]:
    """Every registered route, with included routers flattened (FastAPI keeps an included
    router as one entry in `app.routes`; this is how its OpenAPI generator walks them)."""
    return list(iter_route_contexts(app.routes))


def _endpoints() -> list[tuple[str, str]]:
    """(method, path with every `{param}` filled in) for each registered `/api` route."""
    found = []
    for route in _routes():
        if not (route.path or "").startswith("/api"):
            continue
        kind = route.original_route
        assert isinstance(kind, APIRoute | Route), f"{kind!r}: unknown route type under /api"
        for method in sorted(route.methods or ()):
            if method == "HEAD":
                continue
            found.append((method, re.sub(r"\{[^}]+\}", "x", route.path)))
    return found


def test_no_sub_app_is_mounted_under_api() -> None:
    """A mounted app's routes aren't listed, so the enumeration below couldn't see them."""
    assert not [r for r in _routes() if isinstance(r.original_route, Mount)]


def test_the_public_routes_are_exactly_the_specs() -> None:
    assert is_public("GET", "/api/health")
    assert is_public("POST", "/api/auth/login")
    assert is_public("GET", "/api/auth/invites/some-token")
    # Built by #8 (request access); named here so it's public the day it lands.
    assert is_public("POST", "/api/access-requests")

    assert not is_public("POST", "/api/health")
    assert not is_public("GET", "/api/access-requests")
    assert not is_public("GET", "/api/auth")  # only paths under /api/auth/
    assert not is_public("GET", "/api/authz")
    assert not is_public("GET", "/api/runs")


def test_only_paths_under_api_admin_skip_the_gate_for_require_admin() -> None:
    assert is_admin_path("/api/admin/users")
    assert is_admin_path("/api/admin/access-requests/1/grant")
    assert not is_admin_path("/api/admin")  # no route; only paths under /api/admin/
    assert not is_admin_path("/api/administrator")
    assert not is_admin_path("/api/adminx/users")
    assert not is_admin_path("/api/runs/admin/x")
    assert not is_public("GET", "/api/admin/users")


@pytest.mark.parametrize(("method", "path"), _endpoints())
async def test_every_route_but_the_public_ones_needs_a_session(method: str, path: str) -> None:
    if is_public(method, path):
        pytest.skip("public by SPEC.md")
    # X-Requested-With is sent, so the CSRF guard's 403 can't stand in for the 401.
    async with client(signed_in=False) as c:
        res = await c.request(method, path, json={})
    if is_admin_path(path):  # require_admin, not the gate: the same 404 as an unknown route
        assert res.status_code == 404, f"{method} {path} -> {res.status_code}"
        assert res.json() == {"detail": "Not Found"}
        return
    assert res.status_code == 401, f"{method} {path} -> {res.status_code}"
    assert res.json() == {"detail": "Sign in first"}


def test_the_enumeration_sees_the_routes_it_should() -> None:
    endpoints = set(_endpoints())
    assert ("GET", "/api/runs/x/events") in endpoints  # the SSE stream
    assert ("POST", "/api/match") in endpoints
    assert ("GET", "/api/health") in endpoints
    assert ("POST", "/api/auth/login") in endpoints
    assert ("GET", "/api/admin/users") in endpoints
    assert ("POST", "/api/admin/access-requests/x/grant") in endpoints
    assert len(endpoints) > 25


async def test_health_and_sign_in_stay_open() -> None:
    async with client(signed_in=False) as c:
        assert (await c.get("/api/health")).status_code == 200
        assert (await c.get("/api/auth/me")).status_code == 401  # its own 401, not the gate's
        login = await c.post("/api/auth/login", json={"email": "a@b.c", "password": "x" * 12})
        assert login.status_code == 401


async def test_a_signed_in_browser_reads_runs() -> None:
    async with client() as c:
        res = await c.get("/api/runs")
    assert res.status_code == 200


async def test_the_trace_stream_works_with_the_session_cookie() -> None:
    run_id = store.create_run("match", {})
    store.finish_run(run_id, "done", result={})
    async with client() as c:
        res = await c.get(f"/api/runs/{run_id}/events")
    assert res.status_code == 200
    assert [m.event for m in parse_sse(res.text)] == ["done"]
    async with client(signed_in=False) as c:
        assert (await c.get(f"/api/runs/{run_id}/events")).status_code == 401
