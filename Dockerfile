# One image serves the whole application: the frontend is built to static
# assets and served by the same FastAPI process that serves the API (HLD AD-5).
# One deploy, one URL, no CORS — and docker-compose.yml then describes the
# thing that is actually deployed rather than an approximation of it.

# ----------------------------------------------------------- frontend build
FROM node:24-slim AS frontend

WORKDIR /build
# Dependencies first, so a source change does not reinstall them.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY openapi.yaml /openapi.yaml
COPY frontend/ ./
# The client must match the contract in the image too, not only in CI.
RUN npm run build


# ------------------------------------------------------------ python build
FROM python:3.12-slim AS backend

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

# Built at /app, which is also where it runs. A virtualenv bakes absolute
# paths into its console-script shebangs, so building at /build and copying to
# /app leaves every entry point pointing at a directory that no longer exists —
# "alembic: not found" at container start, with the binary sitting right there.
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/README.md* ./
# Dependencies as their own layer, without the project, so editing source does
# not reinstall the world.
RUN uv sync --locked --no-dev --no-install-project

COPY backend/ ./
RUN uv sync --locked --no-dev


# ------------------------------------------------------------------ runtime
FROM python:3.12-slim AS runtime

# Which release this image is. Passed by the deploy workflow as the short SHA
# of the commit being deployed, so an alert payload names something that can be
# checked out and rolled back. "dev" when nobody said — a build that does not
# know its version should say so rather than claim one.
ARG RATION_VERSION=dev

# A non-root user, created before anything is copied so ownership is right.
RUN useradd --create-home --uid 10001 ration

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RATION_STATIC_DIR=/app/static \
    RATION_VERSION=${RATION_VERSION}

WORKDIR /app
COPY --from=backend --chown=ration:ration /app/.venv /app/.venv
COPY --from=backend --chown=ration:ration /app/src /app/src
COPY --from=backend --chown=ration:ration /app/migrations /app/migrations
COPY --from=backend --chown=ration:ration /app/alembic.ini /app/alembic.ini
COPY --from=frontend --chown=ration:ration /build/dist /app/static

USER ration
EXPOSE 8000

# No secrets baked in: RATION_DATABASE_URL, RATION_SESSION_SECRET and
# RATION_ENV all come from the environment.
CMD ["uvicorn", "ration.api.app:application", "--host", "0.0.0.0", "--port", "8000"]
