"""Configuration, the attribute allowlist, and what happens when it is off (#56)."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ration.config import Settings
from ration.observability import names, telemetry
from ration.observability.attributes import ALLOWED, ForbiddenAttributeError, checked


@pytest.fixture(autouse=True)
def _no_leftover_provider():  # type: ignore[no-untyped-def]
    yield
    telemetry.shutdown()


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "sqlite://",
        "environment": "development",
        "session_secret": "x",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


class TestTheAllowlist:
    def test_an_allowed_key_passes_through(self) -> None:
        assert checked({"http.route": "/api/plans/{plan_id}/shopping-list"}) == {
            "http.route": "/api/plans/{plan_id}/shopping-list"
        }

    def test_an_unlisted_key_raises(self) -> None:
        with pytest.raises(ForbiddenAttributeError) as raised:
            checked({"ration.ingredient_name": "Куриная грудка"})
        assert "ration.ingredient_name" in str(raised.value)

    def test_an_unlisted_key_is_dropped_rather_than_raised_when_not_strict(self) -> None:
        """In production a telemetry mistake degrades telemetry, not the request."""
        with pytest.warns(RuntimeWarning, match="ration.plan_id"):
            assert checked({"ration.plan_id": "abc"}, strict=False) == {}

    def test_the_warning_names_the_key_and_not_the_value(self) -> None:
        with pytest.warns(RuntimeWarning) as warnings:
            checked({"ration.plan_id": "a-real-plan-id"}, strict=False)
        assert "a-real-plan-id" not in str(warnings[0].message)

    def test_nothing_that_identifies_a_person_or_a_meal_is_allowed(self) -> None:
        for forbidden in (
            "ration.plan_id",
            "ration.ingredient_id",
            "ration.ingredient_name",
            "ration.module_name",
            "ration.kcal",
            "ration.protein_g",
            "user.email",
            "url.path",
            "url.query",
            "http.target",
            "exception.message",
            "exception.stacktrace",
        ):
            assert forbidden not in ALLOWED


class TestOffByDefault:
    def test_telemetry_is_off_unless_asked_for(self) -> None:
        telemetry.configure(_settings())
        assert telemetry.is_enabled() is False
        assert telemetry.tracer() is None

    def test_a_stage_with_telemetry_off_does_nothing_and_still_runs_its_body(self) -> None:
        telemetry.configure(_settings())
        ran = False
        with telemetry.stage(names.CONVERT_YIELD, items_in=3) as recorder:
            ran = True
            recorder.count(3)
        assert ran

    def test_a_stage_with_telemetry_off_still_lets_an_exception_through(self) -> None:
        with pytest.raises(ValueError), telemetry.stage(names.CONVERT_YIELD):
            raise ValueError("boom")


class TestWhenItIsOn:
    def test_the_resource_names_the_service_version_and_environment(self) -> None:
        telemetry.configure(
            _settings(
                telemetry_enabled=True,
                environment="staging",
                service_name="ration-api",
                service_version="abc1234",
            )
        )
        assert telemetry.is_enabled()
        resource = telemetry._provider.resource.attributes  # type: ignore[union-attr]
        assert resource["service.name"] == "ration-api"
        assert resource["service.version"] == "abc1234"
        assert resource["deployment.environment"] == "staging"

    def test_a_stage_records_its_counts(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        telemetry.install(provider)

        with telemetry.stage(names.EXPAND_ENTRIES, items_in=27) as recorder:
            recorder.count(114)

        (span,) = exporter.get_finished_spans()
        assert span.attributes["ration.items_in"] == 27
        assert span.attributes["ration.items_out"] == 114

    def test_a_raising_stage_records_the_class_and_never_the_message(self) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        telemetry.install(provider)

        with pytest.raises(ValueError), telemetry.stage(names.CONVERT_YIELD):
            raise ValueError("Куриная грудка has unit 'tbsp'")

        (span,) = exporter.get_finished_spans()
        assert span.attributes["exception.type"] == "ValueError"
        assert "Куриная грудка" not in str(span.attributes)
        assert "Куриная грудка" not in str([event.attributes for event in span.events])

    def test_the_global_tracer_provider_is_left_alone(self) -> None:
        """FastAPI instruments itself off the global one, and leaks the raw path."""
        from opentelemetry import trace

        provider = TracerProvider()
        telemetry.install(provider)
        assert trace.get_tracer_provider() is not provider


class TestTheStageNames:
    def test_there_are_eight_of_them_and_they_are_unique(self) -> None:
        assert len(names.SHOPPING_LIST_STAGES) == 8
        assert len(set(names.SHOPPING_LIST_STAGES)) == 8
