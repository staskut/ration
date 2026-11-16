"""Tracer setup, and the one helper every pipeline stage is timed with.

Telemetry is off unless the environment asks for it (HLD §6). Off means off:
no provider, no exporter, no background thread and no span — `stage()` becomes
a context manager that does nothing, so an application with telemetry disabled
takes the same path it took before any of this existed.

Export is OTLP over HTTP to the collector. Failures there are swallowed by the
SDK's batch processor on its own thread; a request never waits on an exporter
and never fails because one is unreachable. That is the whole reason the batch
processor is used rather than the simple one.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Status, StatusCode, Tracer

from ration.observability.attributes import checked, set_strict

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ration.config import Settings

_tracer: Tracer | None = None
_provider: TracerProvider | None = None


def configure(settings: Settings) -> None:
    """Start tracing, if this environment wants it. Idempotent."""
    if not settings.telemetry_enabled or _tracer is not None:
        return

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        checked(
            {
                "service.name": settings.service_name,
                "service.version": settings.service_version,
                "deployment.environment": settings.environment,
            }
        )
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{settings.otlp_endpoint}/v1/traces"))
    )
    # A forbidden attribute key is a programming error, and in production a
    # programming error in telemetry must not reach the person using the app.
    install(provider, strict=not settings.is_production)


def install(provider: TracerProvider, *, strict: bool = True) -> None:
    """Point *this application's* tracing at `provider`.

    The global tracer provider is deliberately left unset, which is the one
    surprising line in this package and the reason it has this comment.

    FastAPI 0.143 instruments itself when a global provider exists, and its
    server span carries `url.path` — the **raw** path, which for the
    instrumented route reads `/api/plans/<a plan id>/shopping-list`. A plan id
    is a handle on one real person's dietary record, and HLD §8 says telemetry
    never carries it. Setting the global provider would therefore ship the
    exact thing this project forbids, from a library nobody chose to enable,
    with no allowlist in front of it.

    So the tracer is taken from the provider directly and the global is left as
    the no-op it starts as. The cost is real and worth naming: any library
    instrumented through the OTel global — including FastAPI's own dependency,
    endpoint and serialisation spans — stays silent. In exchange, every span
    this service exports was written here and passed `attributes.checked()`.
    Collector-side redaction would let both be true at once; that is #67.
    """
    global _tracer, _provider
    _provider = provider
    _tracer = provider.get_tracer("ration")
    set_strict(strict)


def shutdown() -> None:
    """Flush and detach. Safe to call when nothing was ever configured."""
    global _tracer, _provider
    if _provider is not None:
        _provider.shutdown()
    _tracer = None
    _provider = None


def is_enabled() -> bool:
    return _tracer is not None


def tracer() -> Tracer | None:
    return _tracer


@dataclass(slots=True)
class StageRecorder:
    """Handed to a stage so it can report how much work it turned out to be.

    Counts only. `ration.items_out` is set after the stage runs, because the
    size of a stage's output is the thing you cannot know in advance and the
    thing you want when a stage is slow.
    """

    _span: trace.Span | None = None

    def count(self, items_out: int) -> None:
        if self._span is not None:
            self._span.set_attributes(checked({"ration.items_out": items_out}))


@contextmanager
def stage(name: str, *, items_in: int | None = None) -> Iterator[StageRecorder]:
    """Time one pipeline stage as a span, or do nothing if telemetry is off.

    An exception leaving the stage marks the span ERROR and records the
    exception's **class name only**. Not its message: the staged incident of
    this milestone is an unrecognised unit reaching the raw-weight conversion,
    and that message names the catalog row it choked on. A span that carries it
    would put one person's dietary record into Tempo, which is the single thing
    HLD §8 forbids. The class name plus the stage is enough to diagnose; the
    row is found against the database, by a human, with a runbook.
    """
    current = _tracer
    if current is None:
        yield StageRecorder()
        return

    attributes = {"ration.stage": name}
    if items_in is not None:
        attributes["ration.items_in"] = items_in  # type: ignore[assignment]

    with current.start_as_current_span(
        name,
        attributes=checked(attributes),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield StageRecorder(span)
        except BaseException as exc:
            mark_failed(span, exc)
            raise
        else:
            span.set_status(Status(StatusCode.OK))


def mark_failed(span: trace.Span, exc: BaseException) -> None:
    """Record a failure on `span` without recording what the failure said."""
    name = type(exc).__name__
    span.set_attributes(checked({"exception.type": name}))
    span.add_event("exception", attributes=checked({"exception.type": name}))
    span.set_status(Status(StatusCode.ERROR, name))
