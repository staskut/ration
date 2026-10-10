"""One error shape for the whole API.

Matches the `Error` schema in openapi.yaml. Messages are English and aimed at
developers; the follower's screens render their own text from a code, because
they are Russian and a server-built sentence would be untranslatable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    code: str
    field: str | None = None


class ApiError(Exception):
    """An error with a status code and a stable machine-readable code.

    A plain Exception subclass rather than a dataclass: combining
    ``@dataclass(frozen=True)`` with ``Exception`` breaks ``BaseException``'s own
    initialisation, and the failure surfaces much later as a confusing
    ``super(type, obj)`` TypeError inside the exception handler.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: tuple[ErrorDetail, ...] = (),
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = [
                {k: v for k, v in (("field", d.field), ("code", d.code)) if v is not None}
                for d in self.details
            ]
        return {"error": payload}


def unauthorized(message: str = "Authentication required") -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", message)


def forbidden(message: str = "This action is not available to your role") -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def not_found(what: str = "Resource") -> ApiError:
    """404 is also the answer for another profile's data.

    Returning 403 there would confirm the resource exists, which is a disclosure
    the API has no reason to make.
    """
    return ApiError(404, "NOT_FOUND", f"{what} not found")


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)


def unprocessable(code: str, message: str, *details: ErrorDetail) -> ApiError:
    return ApiError(422, code, message, tuple(details))


async def api_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


async def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Keep FastAPI's own errors in the same shape as ours."""
    assert isinstance(exc, HTTPException)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}},
    )


async def validation_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    errors = getattr(exc, "errors", lambda: [])()
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_FAILED",
                "message": "The request body did not match the contract",
                "details": [
                    {
                        "field": ".".join(str(part) for part in error.get("loc", ())[1:]),
                        "code": error.get("type", "invalid"),
                    }
                    for error in errors
                ],
            }
        },
    )
