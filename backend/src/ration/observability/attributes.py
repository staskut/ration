"""The complete list of keys telemetry is allowed to carry, and the gate.

HLD §8: the database holds dietary and health-adjacent data for one real
person. It is never logged and never included in telemetry attributes.

That rule is easy to keep by accident and easy to break by accident, so it is
written here as data rather than left as a convention. Every span attribute,
every metric attribute and every structured log field the application sets goes
through `checked()`. A key that is not in `SOURCES` is a defect: it raises in
development and in tests, and in production it is dropped and logged — by key,
never by value — because telemetry must never turn a working request into a
500.

Each key says where its value comes from, and **none of those sources is a
database row**. That is the property worth checking when reading this table: a
key whose value could only have been obtained by reading the plan, the catalog
or the profile does not belong here, whatever it is called.

What is excluded is as deliberate as what is allowed:

*   **Names.** Ingredient and module names are what somebody eats.
*   **Figures.** Calories, protein, targets, portion factors.
*   **Ratings and feedback.** The follower's opinion of a meal.
*   **Identifiers, opaque or not.** There is one real user; a stable plan id is
    a stable handle on one person's dietary record. Counts are not identifiers.
*   **Raw paths, query strings, request and response bodies.** A raw path
    carries a plan id, which is why routes are labelled by template.
*   **Exception messages.** `exception.frames` carries where the code broke;
    `exception.stacktrace` would end with the message, and in the staged
    incident of #60 that message names the catalog row that failed.

Counts survive the cut because "this stage took 400 ms" is uninterpretable
without "this stage had 38 rows", and a row count names nobody.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Final

_logger = logging.getLogger("ration.observability")

#: Resource attributes, set once per process rather than per signal.
RESOURCE_SOURCES: Final[Mapping[str, str]] = {
    "service.name": "Settings.service_name, from RATION_SERVICE_NAME",
    "service.version": "Settings.service_version, from RATION_VERSION at build time",
    "deployment.environment": "Settings.environment, from RATION_ENV",
}

#: Everything the application may attach to a span, a metric point or a log
#: record, and where each value comes from.
SOURCES: Final[Mapping[str, str]] = {
    **RESOURCE_SOURCES,
    # --- the request, by template only
    "http.request.method": "the ASGI scope's method",
    "http.route": "the matched route's template; never scope['path']",
    "http.response.status_code": "the status of the response that was sent",
    "duration_ms": "a monotonic clock either side of the request",
    # --- correlation: the ids, not what they point at
    "trace_id": "the current span's trace id, as hex",
    "span_id": "the current span's id, as hex",
    # --- the pipeline, by name and by size
    "ration.stage": "a constant from observability/names.py",
    "ration.items_in": "len() of the stage's input",
    "ration.items_out": "len() of the stage's output",
    # --- failure, by shape
    "exception.type": "type(exc).__name__",
    "exception.frames": "traceback frames only; never the exception's message",
    # --- where a log record was written, from the logging module's own frame
    # information. Code locations, not data: the same three fields a traceback
    # frame carries, and chosen for the same reason (see logs.exception_frames).
    "code.filepath": "logging's record.pathname",
    "code.lineno": "logging's record.lineno",
    "code.function": "logging's record.funcName",
    # --- the shape of a log record itself
    "timestamp": "the logging module's clock",
    "level": "the logging level the call used",
    "logger": "the logger's name",
    "message": "a constant from observability/logs.py Message",
    "telemetry.dropped_key": "the name of a key this gate refused; never its value",
}

#: The one message this module logs. `logs.Message` re-exports it, so the set
#: of messages the service can emit stays a single closed list.
DROPPED_MESSAGE: Final = "telemetry.attribute_dropped"

ALLOWED: Final[frozenset[str]] = frozenset(SOURCES)


class ForbiddenAttributeError(AssertionError):
    """A telemetry key that is not on the allowlist was set."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"{key!r} is not an allowed telemetry attribute. Telemetry may carry no "
            f"dietary or profile data (HLD §8). Add the key to SOURCES in "
            f"ration/observability/attributes.py only if it cannot identify a person "
            f"or describe what they eat — and say there where its value comes from."
        )
        self.key = key


def checked(attributes: Mapping[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Return `attributes` with every key verified against the allowlist.

    `strict` is on everywhere but production, where a key slipping through is
    dropped rather than raised: a telemetry mistake must degrade the telemetry,
    never the request. The warning names the key and not the value, because the
    value is the part that might be somebody's dinner.
    """
    safe: dict[str, Any] = {}
    for key, value in attributes.items():
        if key in ALLOWED:
            safe[key] = value
            continue
        if strict:
            raise ForbiddenAttributeError(key)
        # `logging.config.fileConfig` disables every logger it does not name,
        # and Alembic calls it on each migration run. A warning about a
        # telemetry leak is the last warning that should go missing because
        # something else reconfigured logging.
        _logger.disabled = False
        _logger.warning(DROPPED_MESSAGE, extra={"telemetry.dropped_key": key})
    return safe
