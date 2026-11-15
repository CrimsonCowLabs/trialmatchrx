"""FastAPI app: routers, CORS, startup."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.config import get_settings
from app.db import init_db
from app.routers import eval as eval_routes
from app.routers import feasibility, match, runs, trials
from app.schemas import Health


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
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

for module in (match, runs, trials, feasibility, eval_routes):
    app.include_router(module.router)


@app.get("/api/health", response_model=Health, tags=["health"])
async def health() -> Health:
    settings = get_settings()
    return Health(ok=True, demo_mode=settings.demo_mode, model_ids=settings.model_ids())
