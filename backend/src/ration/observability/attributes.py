"""The complete list of keys telemetry is allowed to carry, and the gate.

HLD §8: the database holds dietary and health-adjacent data for one real
person. It is never logged and never included in telemetry attributes.

That rule is easy to keep by accident and easy to break by accident, so it is
written here as data rather than left as a convention. Every span attribute,
metric attribute and structured log field the application sets goes through
`checked()`. A key that is not on `ALLOWED` is a defect: it raises in
development and in tests, and in production it is dropped with a warning that
names the key and nothing else — telemetry must never turn a working request
into a 500.

What is excluded is as deliberate as what is allowed:

*   **Names.** Ingredient and module names are what somebody eats.
*   **Figures.** Calories, protein, targets, portion factors.
*   **Ratings and feedback.** The follower's opinion of a meal.
*   **Identifiers, opaque or not.** There is one real user; a stable plan id is
    a stable handle on one person's dietary record. Counts are not identifiers.
*   **Raw paths, query strings, request and response bodies.** A raw path
    carries a plan id, which is why routes are labelled by template.

Counts survive the cut because "this stage took 400 ms" is uninterpretable
without "this stage had 38 rows", and a row count names nobody.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import Any

#: Resource attributes, set once per process rather than per span.
RESOURCE_KEYS = frozenset(
    {
        "service.name",
        "service.version",
        "deployment.environment",
    }
)

#: Per-signal attributes. Everything the application may attach to a span, a
#: metric point or a log record.
ALLOWED = (
    frozenset(
        {
            # HTTP, by route template only.
            "http.request.method",
            "http.route",
            "http.response.status_code",
            # Correlation. The ids themselves, not what they point at.
            "trace_id",
            "span_id",
            # The pipeline stage this span or record belongs to.
            "ration.stage",
            # Size of work. Counts of rows, never the rows.
            "ration.items_in",
            "ration.items_out",
            # How long, in milliseconds, for the log record that mirrors the span.
            "duration_ms",
            # The class name of an unhandled exception. Not its message: in the
            # staged incident of #60 the message names the offending catalog row.
            "exception.type",
        }
    )
    | RESOURCE_KEYS
)


class ForbiddenAttributeError(AssertionError):
    """A telemetry key that is not on the allowlist was set."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"{key!r} is not an allowed telemetry attribute. Telemetry may carry no "
            f"dietary or profile data (HLD §8). Add the key to ALLOWED in "
            f"ration/observability/attributes.py only if it cannot identify a person "
            f"or describe what they eat."
        )
        self.key = key


def checked(attributes: Mapping[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Return `attributes` with every key verified against the allowlist.

    `strict` is on everywhere but production, where a key slipping through is
    dropped rather than raised: a telemetry mistake must degrade the telemetry,
    never the request.
    """
    safe: dict[str, Any] = {}
    for key, value in attributes.items():
        if key in ALLOWED:
            safe[key] = value
            continue
        if strict:
            raise ForbiddenAttributeError(key)
        warnings.warn(
            f"dropped telemetry attribute {key!r}: not on the allowlist",
            RuntimeWarning,
            stacklevel=2,
        )
    return safe
