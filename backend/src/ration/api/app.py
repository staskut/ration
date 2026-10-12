"""Application assembly.

FastAPI is told not to generate its own schema: openapi.yaml is hand-written and
is the contract (HLD AD-2). Serving a generated one here would create a second,
subtly different description of the same API and quietly undermine the drift
check the frontend depends on.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from ration.api.errors import (
    ApiError,
    api_error_handler,
    http_exception_handler,
    validation_exception_handler,
)
from ration.api.routers import auth, ingredients
from ration.config import settings
from ration.repositories.database import make_engine, make_session_factory


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(
        title="Ration API",
        version="0.1.0",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    engine = make_engine(database_url or settings().database_url)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    app.include_router(auth.router, prefix="/api")
    app.include_router(ingredients.router, prefix="/api")

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
