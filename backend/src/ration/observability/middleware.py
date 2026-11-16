"""One span, one metric point and two log lines per HTTP request.

All three carry the same route template and the same trace id, which is what
makes them joinable: a slow route found in the metrics leads to a trace, and
the trace's id finds the log lines for that exact request (HLD §7).

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
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry.trace import SpanKind

from ration.observability import logs, metrics, names, telemetry
from ration.observability.attributes import checked

#: The label for a request that matched no route. One fixed string, so a
#: hundred probes for /wp-login.php cannot become a hundred time series.
UNMATCHED_ROUTE = "unmatched"

#: Paths that are measured but not logged. A liveness probe every few seconds
#: would otherwise be most of the log volume and none of its information.
UNLOGGED = frozenset({"/health"})

#: `{plan_id}` and `{full_path:path}` alike.
_PARAMETER = re.compile(r"\{([^{}:]+)(?::[^{}]+)?\}")


class TracingMiddleware:
    """Wraps the application in a server span, a timing and two log lines."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not (telemetry.is_enabled() or metrics.is_enabled()):
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        status: dict[str, int] = {}

        async def record_status(message: Any) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        started = time.perf_counter()
        with _span(method) as span:
            quiet = scope.get("path", "") in UNLOGGED
            if not quiet:
                logs.logger().debug(
                    logs.Message.REQUEST_STARTED,
                    extra=checked({"http.request.method": method}),
                )
            try:
                await self.app(scope, receive, record_status)
            except BaseException as exc:
                # An exception that escapes the application is a 500 whether or
                # not a response start was ever sent.
                self._finish(span, scope, method, 500, started, quiet, exc)
                raise
            self._finish(span, scope, method, status.get("code", 0), started, quiet, None)

    def _finish(
        self,
        span: Any,
        scope: Any,
        method: str,
        code: int,
        started: float,
        quiet: bool,
        exc: BaseException | None,
    ) -> None:
        """Close the three signals together, so they agree with each other."""
        elapsed = time.perf_counter() - started
        template = route_template(scope)

        if span is not None:
            _name(span, scope)
            span.set_attributes(checked({"http.response.status_code": code}))
            if exc is not None:
                telemetry.mark_failed(span, exc)

        metrics.record_request(method=method, route=template, status_code=code, seconds=elapsed)

        if quiet:
            return
        fields = {
            "http.request.method": method,
            "http.route": template,
            "http.response.status_code": code,
            "duration_ms": round(elapsed * 1000, 1),
        }
        if exc is not None:
            # Only an exception nothing converted into a response reaches here:
            # ApiError and HTTPException are handled in api/errors.py and leave
            # as an ordinary status code.
            logs.failed(exc, **fields)
        else:
            logs.logger().info(logs.Message.REQUEST_FINISHED, extra=checked(fields))


@contextmanager
def _span(method: str) -> Iterator[Any]:
    """The request span, or nothing when only metrics are on."""
    tracer = telemetry.tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(
        names.REQUEST_SPAN,
        kind=SpanKind.SERVER,
        attributes=checked({"http.request.method": method}),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        yield span


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
