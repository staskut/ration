"""Application assembly.

FastAPI is told not to generate its own schema: openapi.yaml is hand-written and
is the contract (HLD AD-2). Serving a generated one here would create a second,
subtly different description of the same API and quietly undermine the drift
check the frontend depends on.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ration.api import ws
from ration.api.errors import (
    ApiError,
    api_error_handler,
    http_exception_handler,
    validation_exception_handler,
)
from ration.api.routers import (
    auth,
    derived,
    follower,
    ingredients,
    modules,
    plans,
    profiles,
)
from ration.config import settings
from ration.observability import logs, metrics, telemetry
from ration.observability.middleware import TracingMiddleware
from ration.repositories.database import make_engine, make_session_factory


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Remember the running loop so synchronous handlers can reach it.

    A sync handler runs in a threadpool worker with no loop of its own, so
    without this every WebSocket broadcast is dropped — silently, and
    invisibly to any request-level test.
    """
    app.state.event_loop = asyncio.get_running_loop()
    yield


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(
        lifespan=_lifespan,
        title="Ration API",
        version="0.1.0",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    # Telemetry is off unless this environment asked for it (HLD §6). When it
    # is off nothing is installed: no provider, no exporter, no middleware, and
    # therefore no spans — the application takes exactly the path it took
    # before any of this existed.
    telemetry.configure(settings())
    metrics.configure(settings())
    logs.configure(settings())
    if telemetry.is_enabled() or metrics.is_enabled():
        app.add_middleware(TracingMiddleware)

    engine = make_engine(database_url or settings().database_url)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.plan_hub = ws.PlanHub()

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    app.include_router(auth.router, prefix="/api")
    app.include_router(ingredients.router, prefix="/api")
    app.include_router(modules.router, prefix="/api")
    app.include_router(profiles.router, prefix="/api")
    app.include_router(plans.router, prefix="/api")
    app.include_router(derived.router, prefix="/api")
    app.include_router(follower.router, prefix="/api")
    app.include_router(ws.router, prefix="/api")

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        """Liveness, and which release is answering.

        The version is here because telemetry is not everywhere yet (#62): a
        Fly machine ships no signals, so the only way to ask a deployed
        environment what it is running is to ask it directly. It is out of
        `openapi.yaml` on purpose — `include_in_schema=False` — so this adds
        nothing to the contract and regenerates no client.
        """
        return {"status": "ok", "version": settings().service_version}

    _serve_frontend(app)
    return app


def _serve_frontend(app: FastAPI) -> None:
    """Serve the built single-page app, when there is one.

    Absent in development, where Vite serves it and proxies /api here.

    Two rules matter. An unknown path under /api is a JSON 404, never the SPA —
    a client fetching a mistyped endpoint should get an error it can parse, not
    an HTML page that fails to deserialise three frames later. Any other
    unknown path falls through to index.html, so a deep link survives a reload.
    """
    static_dir = (
        Path(os.environ.get("RATION_STATIC_DIR", ""))
        if os.environ.get("RATION_STATIC_DIR")
        else None
    )
    if static_dir is None or not static_dir.is_dir():
        return

    index = static_dir / "index.html"
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise ApiError(404, "NOT_FOUND", "No such endpoint")
        candidate = static_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


application = create_app()
