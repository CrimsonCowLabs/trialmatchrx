"""FastAPI app: routers, CORS, startup."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from app.config import get_settings
from app.db import init_db
from app.routers import eval as eval_routes
from app.routers import feasibility, guide, match, runs, trials
from app.schemas import Health, RunDone
from app.sources.cohort import get_cohort
from app.trace.replay import recorded_patients

SSE_MODELS = [RunDone]  # TraceEvent is already referenced by /trace


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    get_cohort()  # SPEC.md: the feasibility cohort goes into a DataFrame once, at startup
    yield


def _operation_id(route: APIRoute) -> str:
    return route.name  # clean names in the generated TS types


app = FastAPI(
    title="TrialMatch Rx API",
    version="0.1.0",
    lifespan=lifespan,
    generate_unique_id_function=_operation_id,
    separate_input_output_schemas=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Run-Id"],
)

for module in (match, runs, trials, feasibility, eval_routes, guide):
    app.include_router(module.router)


def _openapi() -> dict[str, Any]:
    """FastAPI's schema plus models only the SSE stream uses, so `make types` emits them."""
    if app.openapi_schema is None:
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
            separate_input_output_schemas=False,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for model in SSE_MODELS:
            components[model.__name__] = model.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _openapi  # type: ignore[method-assign]


@app.get("/api/health", response_model=Health, tags=["health"])
async def health() -> Health:
    """In DEMO_MODE=replay `ok` is true once at least one demo patient is recorded, every
    patient with a match recording also has its closer recording, and every fixture file
    loads; `demo_patients` lists the fully recorded patient ids."""
    settings = get_settings()
    ok = True
    patients: list[str] = []
    if settings.demo_mode == "replay":
        try:
            patients, complete = recorded_patients(settings.demo_fixtures_dir)
        except ValueError:  # a file that isn't a valid RunFixture (pydantic ValidationError)
            patients, complete = [], False
        ok = bool(patients) and complete
    return Health(
        ok=ok,
        demo_mode=settings.demo_mode,
        model_ids=settings.model_ids(),
        demo_patients=patients,
    )
