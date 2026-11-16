"""Structured logs, correlated to the trace by id.

One JSON object per line, through the standard library's `logging` — no second
façade, no `print`. Every record written while a request is in flight carries
that request's `trace_id` and `span_id` in the same hex form the exported span
uses, so a log line, a trace and a metric series can be matched to one request.
That correlation is the whole point: three signals that cannot be joined are
three separate guesses.

Two rules make this safe to switch on in production, where the database holds
one real person's dietary record (HLD §8):

*   **The message is a constant.** Every log message is one of the strings in
    `Message`, and everything variable lives in a structured field that has
    passed the allowlist. A formatted message is where a plan id ends up when
    somebody is debugging at speed.
*   **Nobody can route around it.** Uvicorn's access logger prints the raw
    path — `/api/plans/<a plan id>/shopping-list` — and no helper of ours ever
    sees it. When telemetry is on it is silenced, and the structured finish
    record with the route template replaces it.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.sdk._logs import LoggingHandler as OTelLoggingHandler

from ration.observability.attributes import ALLOWED, DROPPED_MESSAGE, checked

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ration.config import Settings

LOGGER_NAME = "ration"

#: Fields every record carries, describing the record rather than the request.
STRUCTURE = ("timestamp", "level", "logger", "message")

_configured = False
_logger_provider: Any = None


class Message(StrEnum):
    """Every log message the application can emit.

    A closed set, so "what can this service print?" is answered by reading one
    enum rather than by grepping for quotation marks.
    """

    REQUEST_STARTED = "request.started"
    REQUEST_FINISHED = "request.finished"
    REQUEST_FAILED = "request.failed"
    TELEMETRY_STARTED = "telemetry.started"
    TELEMETRY_ATTRIBUTE_DROPPED = DROPPED_MESSAGE


class AllowlistedLoggingHandler(OTelLoggingHandler):  # type: ignore[misc,valid-type]
    """The OTLP log handler, with the same allowlist in front of it.

    The SDK builds a record's attributes from everything on the `LogRecord`,
    which is a wider door than the JSON formatter's: anything a caller passes
    in `extra`, and anything the logging module or another library attaches,
    would travel. Running the same list here means one allowlist governs all
    three signals and both log destinations, rather than two that will
    eventually disagree.

    The filtering is silent, which is the one place in this package that drops
    a key without saying so. The warning belongs where a key is *set* — this is
    where the SDK's own bookkeeping arrives, and a warning here would be logged
    on this handler, whose attributes would be filtered, which would warn. That
    is not a hypothetical: it was a RecursionError on the first request.
    """

    @staticmethod
    def _get_attributes(record: logging.LogRecord) -> Any:
        attributes = OTelLoggingHandler._get_attributes(record)
        return {key: value for key, value in attributes.items() if key in ALLOWED}


class TraceCorrelationFilter(logging.Filter):
    """Stamp each record with the ids of the span it was written inside.

    A record written outside a request — at startup, or from a background
    thread — has no span, and gets the all-zero ids rather than another
    request's. Inheriting an id would be worse than having none: it would point
    a reader at the wrong request with no sign that it had.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        context = trace.get_current_span().get_span_context()
        record.trace_id = format(context.trace_id, "032x")
        record.span_id = format(context.span_id, "016x")
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with only allowlisted keys in it."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "0" * 32),
            "span_id": getattr(record, "span_id", "0" * 16),
        }
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key in ALLOWED and key not in payload
        }
        payload.update(extra)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure(settings: Settings) -> None:
    """Install the JSON handler and the shipper, if telemetry is wanted.

    Idempotent, and a no-op when telemetry is off: with it off the application
    installs no handler at all and logs exactly as much as it did before any of
    this existed, which is nothing.

    Two destinations, on purpose. The JSON on stdout is what `docker logs` and
    `fly logs` show, and it is what a person reads when the collector is the
    thing that is broken. The OTLP copy is what reaches Loki, so a trace id
    found in Tempo can be pasted into a log query (HLD §7).
    """
    global _configured
    if not settings.telemetry_enabled or _configured:
        return
    install(level=logging.INFO)
    _ship(settings)
    logging.getLogger(LOGGER_NAME).info(
        Message.TELEMETRY_STARTED,
        extra={"service.name": settings.service_name, "service.version": settings.service_version},
    )


def install(stream: Any = None, level: int = logging.INFO) -> None:
    """Attach the handler to the root logger. The seam tests capture through.

    The level is set on this application's own logger rather than only on the
    root, because the root's level is not ours alone — pytest restores it
    between phases, and a deployment may have its own reason to raise it. A
    level on `ration` decides what this service says about itself.
    """
    global _configured
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(TraceCorrelationFilter())
    handler.setLevel(level)

    logging.getLogger(LOGGER_NAME).setLevel(level)
    _undisable()
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)

    # Uvicorn's access line is the one leak no allowlist can catch, because it
    # never passes through our code: it prints the raw path, plan id included.
    # The structured finish record carries the same request with the route
    # template instead.
    logging.getLogger("uvicorn.access").disabled = True
    # SQLAlchemy's statement logger would print parameter values — every gram
    # of every line of the plan. It is off by default; this says so out loud,
    # so turning it on is a deliberate act and not an inherited default.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    _configured = True


def _ship(settings: Settings) -> None:
    """Send a copy of every record to the collector, for Loki."""
    global _logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.resources import Resource

    provider = LoggerProvider(
        resource=Resource.create(
            checked(
                {
                    "service.name": settings.service_name,
                    "service.version": settings.service_version,
                    "deployment.environment": settings.environment,
                }
            )
        )
    )
    provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{settings.otlp_endpoint}/v1/logs"))
    )
    _logger_provider = provider
    handler = AllowlistedLoggingHandler(level=logging.INFO, logger_provider=provider)
    # On this service's own logger, never on the root one. The OTLP handler
    # runs exporter code, and exporter code logs; on the root logger each of
    # those records would be exported in turn, which is a RecursionError on the
    # first request rather than a subtle leak — it took the stack down on the
    # first try. Attaching here also means Loki holds this service's records
    # rather than every library's.
    logging.getLogger(LOGGER_NAME).addHandler(handler)


def _undisable() -> None:
    """Re-enable this service's loggers, in case something turned them off.

    `logging.config.fileConfig` disables every logger it does not name, and
    Alembic calls it from `migrations/env.py` on each migration run. A service
    whose logs vanish after a deploy that ran a migration is a bad afternoon,
    and the silence looks exactly like "nothing happened".
    """
    for name, logger_ in logging.root.manager.loggerDict.items():
        if isinstance(logger_, logging.Logger) and (
            name == LOGGER_NAME or name.startswith(f"{LOGGER_NAME}.")
        ):
            logger_.disabled = False


def reset() -> None:
    """Remove the handlers. Used between tests; harmless in production."""
    global _configured, _logger_provider
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler.formatter, JsonFormatter):
            root.removeHandler(handler)
    own = logging.getLogger(LOGGER_NAME)
    for handler in list(own.handlers):
        if isinstance(handler, AllowlistedLoggingHandler):
            own.removeHandler(handler)
    if _logger_provider is not None:
        _logger_provider.shutdown()
        _logger_provider = None
    logging.getLogger("uvicorn.access").disabled = False
    logging.getLogger(LOGGER_NAME).setLevel(logging.NOTSET)
    _configured = False


def is_enabled() -> bool:
    return _configured


def logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def exception_frames(exc: BaseException) -> str:
    """Where the code broke: file, line and function, and nothing else.

    Two things are deliberately missing, and both were found by a test rather
    than by foresight:

    `traceback.format_exception` ends with `ValueError: <the message>`, and in
    the staged incident of #60 that message names the catalog row that failed.

    `traceback.format_tb` leaves the message out but prints each frame's
    **source line** — so `raise UnrecognisedUnitError(f"{name} has unit ...")`
    puts the data back in from the other direction, as code. A frame's source
    is written by us, but what it quotes need not be.

    File, line and function locate the failure. The row is found against the
    database, by a human, with a runbook.
    """
    return " <- ".join(
        f"{frame.filename}:{frame.lineno} in {frame.name}"
        for frame in reversed(traceback.extract_tb(exc.__traceback__))
    )


def failed(exc: BaseException, **fields: Any) -> None:
    """Log an exception that nothing converted into a response."""
    logger().error(
        Message.REQUEST_FAILED,
        extra=checked(
            {
                "exception.type": type(exc).__name__,
                "exception.frames": exception_frames(exc),
                **fields,
            },
            strict=False,
        ),
    )
