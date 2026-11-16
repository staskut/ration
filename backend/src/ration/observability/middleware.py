"""One span per HTTP request, named by route template.

The route template is the only form of the path that may be recorded. The raw
path of the instrumented route is `/api/plans/<a plan id>/shopping-list`, and a
plan id is a handle on one real person's dietary record (HLD §8). Starlette
only resolves the template during routing, so the span opens under a provisional
name and is renamed once the application has returned — which is also when the
status code is known.

Pure ASGI rather than `BaseHTTPMiddleware`: this sits in front of every request
including the WebSocket upgrade, and `BaseHTTPMiddleware` buys a task group and
a queue per request for nothing that is needed here.
"""

from __future__ import annotations

import re
from typing import Any

from opentelemetry.trace import SpanKind

from ration.observability import names, telemetry
from ration.observability.attributes import checked

#: The label for a request that matched no route. One fixed string, so a
#: hundred probes for /wp-login.php cannot become a hundred time series.
UNMATCHED_ROUTE = "unmatched"

#: `{plan_id}` and `{full_path:path}` alike.
_PARAMETER = re.compile(r"\{([^{}:]+)(?::[^{}]+)?\}")


class TracingMiddleware:
    """Wraps the application in a server span when telemetry is on."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        tracer = telemetry.tracer()
        if scope["type"] != "http" or tracer is None:
            await self.app(scope, receive, send)
            return

        status: dict[str, int] = {}

        async def record_status(message: Any) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        with tracer.start_as_current_span(
            names.REQUEST_SPAN,
            kind=SpanKind.SERVER,
            attributes=checked({"http.request.method": scope.get("method", "")}),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                await self.app(scope, receive, record_status)
            except BaseException as exc:
                _name(span, scope)
                # An exception that escapes the application is a 500 whether or
                # not a response start was ever sent.
                span.set_attributes(checked({"http.response.status_code": 500}))
                telemetry.mark_failed(span, exc)
                raise
            _name(span, scope)
            code = status.get("code", 0)
            span.set_attributes(checked({"http.response.status_code": code}))


def _name(span: Any, scope: Any) -> None:
    """Rename the span to the matched route template, now that there is one."""
    template = route_template(scope)
    span.update_name(f"{scope.get('method', '')} {template}".strip())
    span.set_attributes(checked({"http.route": template}))


def route_template(scope: Any) -> str:
    """The matched route's template, including the router's prefix.

    This FastAPI keeps an included router mounted rather than flattening it, so
    the matched route's own `path` is missing the `/api` prefix and the scope's
    `root_path` is empty. The prefix is recovered by filling the template's
    parameters from `path_params` and seeing how much of the real path is left
    in front of it — arithmetic on strings, so that the only thing that leaves
    this function is a template. A raw path must never become a label: it
    carries a plan id (HLD §8).
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    if not path:
        return UNMATCHED_ROUTE

    params = scope.get("path_params") or {}
    concrete = _PARAMETER.sub(lambda m: str(params.get(m.group(1), m.group(0))), path)
    full = scope.get("path", "")
    if concrete and full.endswith(concrete):
        return f"{full[: len(full) - len(concrete)]}{path}"
    return path
