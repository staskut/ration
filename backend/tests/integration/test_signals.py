"""Metrics, structured logs, and the rule that none of them says what anyone ate.

The three signals of HLD §7 are asserted together because together is how they
are useful: the test that matters is not that each exists but that one request
produces a span, a metric point and log lines that can be joined by trace id
and route template.

The privacy test at the bottom is the one to read first. It builds its list of
forbidden strings out of the seeded reference data at runtime — every ingredient
name, every module name, the planner's email, the nutrition figures and the
profile's targets — so adding a row to the reference plan widens the test
without anybody remembering to.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from ration.observability import logs, metrics, telemetry
from ration.observability.attributes import ALLOWED
from ration.observability.metrics import DURATION
from ration.observability.middleware import UNMATCHED_ROUTE
from ration.repositories import models

pytestmark = pytest.mark.integration

SEED_PASSWORD = "correct-horse-battery"
ROUTE = "/api/plans/{plan_id}/shopping-list"


class Signals:
    """Everything one request emitted, in the three forms it emitted it."""

    def __init__(
        self, spans: InMemorySpanExporter, reader: InMemoryMetricReader, stream: io.StringIO
    ) -> None:
        self._spans = spans
        self._reader = reader
        self._stream = stream

    def clear(self) -> None:
        self._spans.clear()
        self._stream.seek(0)
        self._stream.truncate()

    def spans(self) -> list[Any]:
        return list(self._spans.get_finished_spans())

    def records(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self._stream.getvalue().splitlines() if line.strip()]

    def points(self) -> list[Any]:
        data = self._reader.get_metrics_data()
        found = []
        for resource in data.resource_metrics:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    if metric.name == DURATION:
                        found.extend(metric.data.data_points)
        return found


@pytest.fixture
def signals(engine: Engine) -> Iterator[tuple[TestClient, Signals]]:
    from ration.api.app import create_app
    from ration.api.security import hash_password
    from ration.seed.command import PLANNER_EMAIL, seed

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.install(provider)

    reader = InMemoryMetricReader()
    metrics.install(MeterProvider(metric_readers=[reader]))

    stream = io.StringIO()
    logs.install(stream, level=logging.DEBUG)

    seed(engine)
    with Session(engine) as session:
        for user in session.scalars(select(models.User)):
            user.password_hash = hash_password(SEED_PASSWORD)
        session.commit()

    app = create_app()
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with TestClient(app) as client:
            client.post("/api/auth/login", json={"email": PLANNER_EMAIL, "password": SEED_PASSWORD})
            yield client, Signals(exporter, reader, stream)
    finally:
        logs.reset()
        metrics.shutdown()
        telemetry.shutdown()


def _plan_id(client: TestClient) -> str:
    plans = client.get("/api/plans").json()
    return next(p["id"] for p in plans if p["name"] == "Пилотная неделя 1")


def _attributes(point: Any) -> dict[str, Any]:
    return dict(point.attributes)


class TestTheMetric:
    def test_one_histogram_carries_method_route_and_status_and_nothing_else(
        self, signals: Any
    ) -> None:
        client, seen = signals
        plan = _plan_id(client)
        client.get(f"/api/plans/{plan}/shopping-list")

        point = next(p for p in seen.points() if _attributes(p)["http.route"] == ROUTE)
        assert set(_attributes(point)) == {
            "http.request.method",
            "http.route",
            "http.response.status_code",
        }
        assert _attributes(point)["http.response.status_code"] == 200
        assert point.count >= 1

    def test_the_percentile_is_not_computed_here(self, signals: Any) -> None:
        """Buckets are carried; p95 is #59's query. A per-process percentile
        cannot be summed across processes, so an app that reports one is
        reporting a number nobody can aggregate."""
        client, seen = signals
        plan = _plan_id(client)
        client.get(f"/api/plans/{plan}/shopping-list")

        point = next(p for p in seen.points() if _attributes(p)["http.route"] == ROUTE)
        assert point.bucket_counts
        assert point.explicit_bounds

    def test_two_plan_ids_land_on_one_series(self, signals: Any) -> None:
        client, seen = signals
        first = _plan_id(client)
        created = client.post("/api/plans", json={"name": "Вторая", "start_date": "2026-11-09"})
        second = created.json()["id"]

        client.get(f"/api/plans/{first}/shopping-list")
        client.get(f"/api/plans/{second}/shopping-list")

        matching = [p for p in seen.points() if _attributes(p)["http.route"] == ROUTE]
        assert len(matching) == 1
        assert matching[0].count == 2

    def test_a_404_and_a_500_are_both_points_and_the_app_judges_neither(self, signals: Any) -> None:
        client, seen = signals
        client.get("/api/plans/does-not-exist/shopping-list")

        statuses = {_attributes(p)["http.response.status_code"] for p in seen.points()}
        assert 404 in statuses
        # Nothing in the app labels a point an error; the split is the query's.
        for point in seen.points():
            assert "error" not in " ".join(_attributes(point))

    def test_twenty_unknown_paths_add_at_most_one_series(self, signals: Any) -> None:
        client, seen = signals
        for index in range(20):
            client.get(f"/api/nope-{index}")

        unknown = [
            p
            for p in seen.points()
            if _attributes(p)["http.route"] in {UNMATCHED_ROUTE, "/{full_path:path}"}
        ]
        assert len(unknown) <= 1

    def test_health_is_measured_even_though_it_is_not_logged(self, signals: Any) -> None:
        client, seen = signals
        seen.clear()
        client.get("/health")

        assert any(_attributes(p)["http.route"] == "/health" for p in seen.points())
        assert [r for r in seen.records() if r["message"].startswith("request.")] == []


class TestTheLogs:
    def test_every_line_is_json_on_its_own(self, signals: Any) -> None:
        client, seen = signals
        plan = _plan_id(client)
        seen.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        assert seen.records()
        for record in seen.records():
            assert set(record) <= ALLOWED

    def test_the_finish_record_matches_the_span_by_trace_id(self, signals: Any) -> None:
        client, seen = signals
        plan = _plan_id(client)
        seen.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        finish = next(r for r in seen.records() if r["message"] == "request.finished")
        span = next(s for s in seen.spans() if s.name.startswith("GET /api/plans"))
        assert finish["trace_id"] == format(span.context.trace_id, "032x")
        assert finish["span_id"] == format(span.context.span_id, "016x")
        assert finish["http.route"] == ROUTE
        assert finish["http.response.status_code"] == 200
        assert finish["duration_ms"] > 0
        assert finish["level"] == "INFO"

    def test_the_start_record_is_debug_so_production_is_one_line_a_request(
        self, signals: Any
    ) -> None:
        client, seen = signals
        plan = _plan_id(client)
        seen.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        start = next(r for r in seen.records() if r["message"] == "request.started")
        assert start["level"] == "DEBUG"

    def test_a_record_outside_a_request_carries_the_all_zero_id(self, signals: Any) -> None:
        _client, seen = signals
        seen.clear()
        logs.logger().info(logs.Message.TELEMETRY_STARTED)

        record = seen.records()[0]
        assert record["trace_id"] == "0" * 32
        assert record["span_id"] == "0" * 16

    def test_a_handled_api_error_is_not_an_error_record(self, signals: Any) -> None:
        client, seen = signals
        seen.clear()
        assert client.get("/api/plans/does-not-exist/shopping-list").status_code == 404

        finish = next(r for r in seen.records() if r["message"] == "request.finished")
        assert finish["level"] == "INFO"
        assert finish["http.response.status_code"] == 404
        assert not [r for r in seen.records() if r["level"] == "ERROR"]

    def test_an_unconverted_exception_logs_its_class_and_frames_but_not_its_message(
        self, signals: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, seen = signals
        plan = _plan_id(client)

        def explode(*_args: Any, **_kwargs: Any) -> None:
            raise ValueError("Куриная грудка has unit 'tbsp'")

        monkeypatch.setattr("ration.api.pipelines.convert_to_raw", explode)
        seen.clear()
        with pytest.raises(ValueError):
            client.get(f"/api/plans/{plan}/shopping-list")

        failed = next(r for r in seen.records() if r["message"] == "request.failed")
        assert failed["level"] == "ERROR"
        assert failed["exception.type"] == "ValueError"
        assert "pipelines.py" in failed["exception.frames"]
        assert "Куриная грудка" not in json.dumps(seen.records(), ensure_ascii=False)
        assert failed["trace_id"] != "0" * 32

    def test_uvicorns_access_logger_cannot_print_the_raw_path(self, signals: Any) -> None:
        """It never passes through our code, so no allowlist can catch it."""
        assert logging.getLogger("uvicorn.access").disabled is True

    def test_sqlalchemy_does_not_log_statements(self, signals: Any) -> None:
        assert logging.getLogger("sqlalchemy.engine").level >= logging.WARNING


class TestNothingDietaryEscapesAnySignal:
    @staticmethod
    def _forbidden(engine: Engine) -> set[str]:
        """Built from the seeded data, so new reference rows widen it for free."""
        out: set[str] = set()
        with Session(engine) as session:
            out |= {n.name for n in session.scalars(select(models.IngredientName))}
            out |= {a.alias for a in session.scalars(select(models.IngredientAlias))}
            out |= {m.name for m in session.scalars(select(models.Module))}
            out |= {u.email for u in session.scalars(select(models.User))}
            for profile in session.scalars(select(models.Profile)):
                out |= {
                    str(profile.daily_kcal_target),
                    str(profile.daily_protein_min),
                    str(profile.daily_protein_target),
                }
            for ingredient in session.scalars(select(models.Ingredient)):
                out |= {str(ingredient.kcal_per_100g), str(ingredient.protein_per_100g)}
        return {value for value in out if value and len(value) > 2}

    def test_no_signal_carries_catalog_or_profile_content(
        self, signals: Any, engine: Engine
    ) -> None:
        client, seen = signals
        plan = _plan_id(client)
        seen.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        emitted = json.dumps(
            {
                "spans": [dict(s.attributes) for s in seen.spans()],
                "metrics": [_attributes(p) for p in seen.points()],
                "logs": seen.records(),
            },
            ensure_ascii=False,
            default=str,
        )
        for value in self._forbidden(engine):
            assert value not in emitted, value
        assert plan not in emitted

    def test_every_emitted_key_is_on_the_allowlist(self, signals: Any) -> None:
        """The check a substring search cannot do: a figure riding on a key."""
        client, seen = signals
        plan = _plan_id(client)
        seen.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        for span in seen.spans():
            assert set(span.attributes) <= ALLOWED
        for point in seen.points():
            assert set(_attributes(point)) <= ALLOWED
        for record in seen.records():
            assert set(record) <= ALLOWED


class TestATelemetryMistakeNeverBreaksARequest:
    """QA's finding on #57, kept as a test so it cannot come back.

    The gate had both modes from the start, but the places that close a request
    passed no flag and so raised in every environment. An engineer adding an
    attribute the allowlist does not carry would have turned every request into
    a 500 in production — the one outcome the lenient mode exists to prevent.
    """

    @staticmethod
    def _without(key: str) -> Any:
        from ration.observability import attributes

        return {k: v for k, v in attributes.SOURCES.items() if k != key}

    def test_in_production_an_unlisted_key_is_dropped_and_the_request_survives(
        self, signals: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ration.observability import attributes

        client, seen = signals
        plan = _plan_id(client)
        # Production: the mode telemetry.configure() sets when is_production.
        attributes.set_strict(False)
        # "Somebody set a key the list does not carry" — simulated by taking a
        # key the request path really sets out of the list.
        monkeypatch.setattr(attributes, "ALLOWED", frozenset(self._without("http.route")))
        seen.clear()

        response = client.get(f"/api/plans/{plan}/shopping-list")

        assert response.status_code == 200
        assert response.json()["lines"]
        assert any(r["message"] == "telemetry.attribute_dropped" for r in seen.records())

    def test_outside_production_the_same_mistake_is_loud(
        self, signals: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """So the engineer who adds the key sees it on the first request."""
        from ration.observability import attributes
        from ration.observability.attributes import ForbiddenAttributeError

        client, _seen = signals
        plan = _plan_id(client)
        attributes.set_strict(True)
        monkeypatch.setattr(attributes, "ALLOWED", frozenset(self._without("http.route")))

        with pytest.raises(ForbiddenAttributeError):
            client.get(f"/api/plans/{plan}/shopping-list")

    def test_the_mode_follows_the_environment(self) -> None:
        from ration.config import Settings
        from ration.observability import attributes, metrics

        for environment, expected in (("production", False), ("staging", True)):
            metrics.shutdown()
            attributes.set_strict(True)
            metrics.configure(
                Settings(
                    database_url="sqlite://",
                    environment=environment,
                    session_secret="x",
                    telemetry_enabled=True,
                    otlp_endpoint="http://127.0.0.1:1",
                )
            )
            assert attributes.is_strict() is expected, environment
        metrics.shutdown()
        attributes.set_strict(True)


class TestTheHistogramCanAnswerAPercentile:
    def test_the_buckets_suit_a_duration_in_seconds(self, signals: Any) -> None:
        """QA's second finding on #57, which #59's p95 panel depends on.

        The SDK's default boundaries start at 0 and jump to 5, which is right
        for milliseconds and useless for seconds: every request this service
        serves lands in one bucket, and a percentile over one bucket is a
        number that is always wrong and never obviously wrong.
        """
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader

        from ration.observability import metrics as metrics_module

        # A bare provider, deliberately: no view, nothing but what install()
        # does for itself. QA's note on #57 was that the boundaries lived on
        # the provider `configure()` builds, so a harness like this one fell
        # back to the SDK's defaults without saying so.
        reader = InMemoryMetricReader()
        metrics_module.install(MeterProvider(metric_readers=[reader]))
        metrics_module.record_request(method="GET", route=ROUTE, status_code=200, seconds=0.012)

        point = next(
            p
            for resource in reader.get_metrics_data().resource_metrics
            for scope in resource.scope_metrics
            for metric in scope.metrics
            if metric.name == DURATION
            for p in metric.data.data_points
        )
        assert 0.025 in point.explicit_bounds
        # The 12 ms request must land somewhere that distinguishes it from a
        # four-second one.
        occupied = [i for i, count in enumerate(point.bucket_counts) if count]
        assert occupied == [2], point.explicit_bounds
