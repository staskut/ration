"""The shopping-list route's trace (#56).

Spans are read back through the SDK's in-memory exporter: no collector, no
listener, no container. What is asserted is what a reviewer would look for in
Tempo — eight stages, in order, under one request span, all closed, carrying
counts and nothing anybody eats.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from ration.observability import names, telemetry
from ration.observability.attributes import ALLOWED
from ration.repositories import models

pytestmark = pytest.mark.integration

SEED_PASSWORD = "correct-horse-battery"


@pytest.fixture
def traced(engine: Engine) -> Iterator[tuple[TestClient, InMemorySpanExporter]]:
    """A logged-in planner against an app with telemetry on."""
    from ration.api.app import create_app
    from ration.api.security import hash_password
    from ration.seed.command import PLANNER_EMAIL, seed

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry.install(provider)

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
            response = client.post(
                "/api/auth/login", json={"email": PLANNER_EMAIL, "password": SEED_PASSWORD}
            )
            assert response.status_code == 204, response.text
            exporter.clear()
            yield client, exporter
    finally:
        telemetry.shutdown()


def _plan_id(client: TestClient) -> str:
    plans = client.get("/api/plans").json()
    return next(p["id"] for p in plans if p["name"] == "Pilot week 1")


def _stages(exporter: InMemorySpanExporter) -> list[Any]:
    return [s for s in exporter.get_finished_spans() if s.name in names.SHOPPING_LIST_STAGES]


def _request_span(exporter: InMemorySpanExporter) -> Any:
    spans = [s for s in exporter.get_finished_spans() if s.name.startswith("GET /api/plans")]
    assert spans, [s.name for s in exporter.get_finished_spans()]
    return spans[-1]


class TestTheTrace:
    def test_one_request_produces_the_eight_pipeline_stages(self, traced: Any) -> None:
        client, exporter = traced
        plan = _plan_id(client)
        exporter.clear()

        assert client.get(f"/api/plans/{plan}/shopping-list").status_code == 200

        assert [s.name for s in _stages(exporter)] == list(names.SHOPPING_LIST_STAGES)

    def test_every_stage_is_a_descendant_of_one_request_span(self, traced: Any) -> None:
        client, exporter = traced
        plan = _plan_id(client)
        exporter.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        request = _request_span(exporter)
        stages = _stages(exporter)
        assert {s.context.trace_id for s in stages} == {request.context.trace_id}
        assert {s.parent.span_id for s in stages} == {request.context.span_id}

    def test_stages_start_in_order_and_all_have_ended(self, traced: Any) -> None:
        client, exporter = traced
        plan = _plan_id(client)
        exporter.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        stages = _stages(exporter)
        starts = [s.start_time for s in stages]
        assert starts == sorted(starts)
        request = _request_span(exporter)
        for span in stages:
            assert span.end_time is not None
            # Closed before the response: every stage ends inside the request.
            assert span.end_time <= request.end_time

    def test_each_stage_says_how_much_work_it_did(self, traced: Any) -> None:
        client, exporter = traced
        plan = _plan_id(client)
        exporter.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        for span in _stages(exporter):
            assert "ration.items_out" in span.attributes, span.name
            assert isinstance(span.attributes["ration.items_out"], int)

    def test_the_request_span_carries_the_route_template_not_the_path(self, traced: Any) -> None:
        client, exporter = traced
        plan = _plan_id(client)
        exporter.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        request = _request_span(exporter)
        assert request.attributes["http.route"] == "/api/plans/{plan_id}/shopping-list"
        assert request.attributes["http.response.status_code"] == 200
        assert plan not in str(request.attributes)

    def test_nothing_but_this_service_writes_spans(self, traced: Any) -> None:
        """FastAPI 0.143 traces itself off the global provider, and its server
        span carries `url.path` — the raw path, with the plan id in it. The app
        never sets the global provider, so those spans do not exist. This is
        the test that fails if somebody sets it (see telemetry.install)."""
        client, exporter = traced
        plan = _plan_id(client)
        exporter.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        spans = exporter.get_finished_spans()
        assert {s.instrumentation_scope.name for s in spans} == {"ration"}
        for span in spans:
            assert plan not in str(dict(span.attributes))


class TestTheAwkwardCases:
    def test_a_failing_stage_is_the_one_marked_error(
        self, traced: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, exporter = traced
        plan = _plan_id(client)

        class UnrecognisedUnitError(ValueError):
            pass

        def explode(*_args: Any, **_kwargs: Any) -> None:
            raise UnrecognisedUnitError("tbsp")

        monkeypatch.setattr("ration.api.pipelines.convert_to_raw", explode)
        exporter.clear()

        with pytest.raises(UnrecognisedUnitError):
            client.get(f"/api/plans/{plan}/shopping-list")

        stages = _stages(exporter)
        assert [s.name for s in stages] == [
            names.LOAD_CATALOG,
            names.LOAD_PLAN,
            names.EXPAND_ENTRIES,
            names.CONVERT_YIELD,
        ]
        failed = stages[-1]
        assert failed.status.status_code is StatusCode.ERROR
        assert failed.attributes["exception.type"] == "UnrecognisedUnitError"
        assert _request_span(exporter).status.status_code is StatusCode.ERROR

    def test_a_failing_stage_records_the_type_but_never_the_message(
        self, traced: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The staged incident's message names the catalog row it choked on."""
        client, exporter = traced
        plan = _plan_id(client)

        def explode(*_args: Any, **_kwargs: Any) -> None:
            raise ValueError("Куриная грудка has unit 'tbsp'")

        monkeypatch.setattr("ration.api.pipelines.convert_to_raw", explode)
        exporter.clear()
        with pytest.raises(ValueError):
            client.get(f"/api/plans/{plan}/shopping-list")

        for span in exporter.get_finished_spans():
            assert "Куриная грудка" not in str(span.attributes)
            assert "Куриная грудка" not in str([e.attributes for e in span.events])

    def test_an_empty_plan_still_runs_every_stage(self, traced: Any, engine: Engine) -> None:
        client, exporter = traced
        created = client.post("/api/plans", json={"name": "Пустая", "start_date": "2026-11-02"})
        assert created.status_code == 201, created.text
        empty = created.json()["id"]
        exporter.clear()

        response = client.get(f"/api/plans/{empty}/shopping-list")
        assert response.status_code == 200
        assert response.json()["lines"] == []
        assert [s.name for s in _stages(exporter)] == list(names.SHOPPING_LIST_STAGES)

    def test_the_check_off_patch_emits_a_well_formed_trace(self, traced: Any) -> None:
        client, exporter = traced
        plan = _plan_id(client)
        first = client.get(f"/api/plans/{plan}/shopping-list").json()["lines"][0]
        exporter.clear()

        response = client.patch(
            f"/api/plans/{plan}/shopping-list/{first['ingredient_id']}",
            json={"checked": True},
        )
        assert response.status_code == 200
        assert [s.name for s in _stages(exporter)] == list(names.SHOPPING_LIST_STAGES)
        assert all(s.end_time is not None for s in exporter.get_finished_spans())


class TestNothingDietaryEscapes:
    def test_no_span_attribute_carries_an_ingredient_or_module_name(
        self, traced: Any, engine: Engine
    ) -> None:
        client, exporter = traced
        plan = _plan_id(client)
        exporter.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        with Session(engine) as session:
            forbidden = {n.name for n in session.scalars(select(models.IngredientName))}
            forbidden |= {m.name for m in session.scalars(select(models.Module))}

        emitted = " ".join(str(s.attributes) for s in exporter.get_finished_spans())
        for word in forbidden:
            assert word not in emitted, word

    def test_every_emitted_key_is_on_the_allowlist(self, traced: Any) -> None:
        client, exporter = traced
        plan = _plan_id(client)
        exporter.clear()
        client.get(f"/api/plans/{plan}/shopping-list")

        for span in exporter.get_finished_spans():
            assert set(span.attributes) <= ALLOWED, (span.name, set(span.attributes) - ALLOWED)


class TestWhenTheCollectorIsNotThere:
    def test_the_request_still_succeeds_with_an_unreachable_endpoint(self, engine: Engine) -> None:
        """A collector that is down degrades telemetry, never the application.

        Port 1 on loopback refuses immediately, which is the fastest honest
        imitation of a collector that is not running. The batch processor
        exports on its own thread, so the request never waits on it.
        """
        from ration.api.app import create_app
        from ration.api.security import hash_password
        from ration.config import Settings
        from ration.seed.command import PLANNER_EMAIL, seed

        telemetry.configure(
            Settings(
                database_url="sqlite://",
                environment="development",
                session_secret="x",
                telemetry_enabled=True,
                otlp_endpoint="http://127.0.0.1:1",
            )
        )
        assert telemetry.is_enabled()

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
                client.post(
                    "/api/auth/login",
                    json={"email": PLANNER_EMAIL, "password": SEED_PASSWORD},
                )
                plan = _plan_id(client)
                response = client.get(f"/api/plans/{plan}/shopping-list")
                assert response.status_code == 200
                assert response.json()["lines"]
        finally:
            telemetry.shutdown()
