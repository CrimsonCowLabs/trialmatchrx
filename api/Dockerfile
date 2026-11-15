# The TrialMatch Rx API, as compose.yaml runs it. Built from the repo root:
#
#   docker build -f api/Dockerfile .
#
# The image keeps the repo's layout (/app/api, /app/data/fixtures) so config.py's default
# paths hold. The database is not in it: DATABASE_URL points at the /data volume.

FROM python:3.12.12-slim-bookworm AS dependencies

COPY --from=ghcr.io/astral-sh/uv:0.8.12 /uv /usr/local/bin/uv

WORKDIR /app/api

# The virtualenv at the path it keeps in the final image (its scripts name the interpreter
# by absolute path). Only the lock and pyproject, so a code change reuses this layer.
ENV UV_PROJECT_ENVIRONMENT=/app/api/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && rm -rf /root/.cache


FROM python:3.12.12-slim-bookworm

ENV PATH=/app/api/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL=sqlite:////data/app.db

RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin trialmatch

WORKDIR /app/api

COPY --from=dependencies /app/api/.venv /app/api/.venv
COPY api/pyproject.toml ./
COPY api/app ./app
# For one-off jobs in the container (`docker compose run --rm api python -m scripts.seed_trials`).
COPY api/scripts ./scripts
COPY data/fixtures /app/data/fixtures

# Docker seeds an empty named volume from the image's mount point, ownership included, so
# SQLite can create app.db (and its -wal / -shm) as the app user.
RUN mkdir -p /data && chown trialmatch:trialmatch /data

USER trialmatch

EXPOSE 8045

# One worker: a run's live trace goes through an in-process bus (app/trace/bus.py), so a
# second worker would serve an events stream that never sees the run. No --reload.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8045", "--workers", "1"]
