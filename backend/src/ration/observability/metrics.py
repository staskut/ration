"""One histogram, and the three signals HLD §7 asks for come out of it.

Request rate is its count. Error rate is its count split by status code. p95 is
a query over its buckets. Adding a counter for "errors" would mean the
application deciding what an error is, and it is not the application's decision:
an expected 404 and an unexpected 500 are the same kind of data point here, and
which of them should wake somebody up is written in the alert (#59), where it
can be read and changed.

The percentile is likewise not computed here. An app that reports its own p95
reports it per process and per scrape interval, and the two cannot be summed.
Buckets can.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry.metrics import Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider

from ration.observability.attributes import checked

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ration.config import Settings

#: OTel's semantic convention name. Prometheus renders it
#: `http_server_request_duration_seconds_bucket`, which is what #59 queries.
DURATION = "http.server.request.duration"

_provider: MeterProvider | None = None
_duration: Histogram | None = None


def configure(settings: Settings) -> None:
    """Start metrics, if this environment wants them. Idempotent."""
    if not settings.telemetry_enabled or _duration is not None:
        return

    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create(
        checked(
            {
                "service.name": settings.service_name,
                "service.version": settings.service_version,
                "deployment.environment": settings.environment,
            }
        )
    )
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{settings.otlp_endpoint}/v1/metrics")
    )
    install(MeterProvider(resource=resource, metric_readers=[reader]))


def install(provider: MeterProvider) -> None:
    """Point metrics at `provider`. The seam tests read in memory through.

    As with tracing, the global meter provider is left unset on purpose — see
    `telemetry.install()` for the reason, which is the same one.
    """
    global _provider, _duration
    _provider = provider
    meter: Meter = provider.get_meter("ration")
    _duration = meter.create_histogram(
        DURATION,
        unit="s",
        description="Duration of an HTTP request, by route template and status.",
    )


def shutdown() -> None:
    global _provider, _duration
    if _provider is not None:
        _provider.shutdown()
    _provider = None
    _duration = None


def is_enabled() -> bool:
    return _duration is not None


def record_request(*, method: str, route: str, status_code: int, seconds: float) -> None:
    """One point. The only metric the application writes."""
    if _duration is None:
        return
    _duration.record(
        seconds,
        attributes=checked(
            {
                "http.request.method": method,
                "http.route": route,
                "http.response.status_code": status_code,
            }
        ),
    )
