"""Per-plan invalidation broadcast (#32)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def plan_id(planner: TestClient) -> str:
    plans = planner.get("/api/plans").json()
    return next(p["id"] for p in plans if p["name"] == "Пилотная неделя 1")


class TestAuthorisation:
    def test_an_unauthenticated_connection_is_closed(
        self, anonymous: TestClient, plan_id: str
    ) -> None:
        from starlette.websockets import WebSocketDisconnect

        with (
            pytest.raises(WebSocketDisconnect) as exc,
            anonymous.websocket_connect(f"/api/ws/plans/{plan_id}"),
        ):
            pass
        assert exc.value.code == 4403

    def test_another_profiles_plan_is_closed(self, planner: TestClient) -> None:
        """Refused without confirming the plan exists, as a 404 would be."""
        from starlette.websockets import WebSocketDisconnect

        with (
            pytest.raises(WebSocketDisconnect),
            planner.websocket_connect("/api/ws/plans/not-mine"),
        ):
            pass

    def test_an_authorised_client_connects(self, planner: TestClient, plan_id: str) -> None:
        with planner.websocket_connect(f"/api/ws/plans/{plan_id}") as socket:
            assert socket is not None


class TestBroadcast:
    """One client, switching identity between calls.

    Two TestClients would mean two event loops, and a broadcast fired on one
    never reaches a socket held by the other. Production has a single process
    and a single loop, so this is the faithful arrangement rather than a
    convenience. Identity is set on the client because starlette is deprecating
    per-request cookies.
    """

    def test_an_entry_change_reaches_a_subscriber(
        self, api: TestClient, cookies_for: dict, plan_id: str
    ) -> None:
        cookies_for.act_as("follower")
        with api.websocket_connect(f"/api/ws/plans/{plan_id}") as socket:
            cookies_for.act_as("planner")
            api.post(
                f"/api/plans/{plan_id}/days/6/entries",
                json={"slot": "dinner", "module_id": "dinner_squid_pepper"},
            )
            message = socket.receive_json()
        assert message["type"] == "invalidate"
        assert message["plan_id"] == plan_id
        assert "entries" in message["changed"]

    def test_the_message_carries_no_payload(
        self, api: TestClient, cookies_for: dict, plan_id: str
    ) -> None:
        """HLD AD-6: clients refetch, so response shapes exist in one place."""
        cookies_for.act_as("follower")
        with api.websocket_connect(f"/api/ws/plans/{plan_id}") as socket:
            cookies_for.act_as("planner")
            api.put(f"/api/plans/{plan_id}/days/6", json={"notes": "x"})
            message = socket.receive_json()
        assert set(message) == {"type", "plan_id", "changed"}

    def test_changed_names_only_the_affected_resources(
        self, api: TestClient, cookies_for: dict, plan_id: str
    ) -> None:
        cookies_for.act_as("follower")
        with api.websocket_connect(f"/api/ws/plans/{plan_id}") as socket:
            cookies_for.act_as("planner")
            api.put(f"/api/plans/{plan_id}/days/6", json={"notes": "y"})
            message = socket.receive_json()
        assert set(message["changed"]) == {"days", "validation"}

    def test_a_follower_rating_reaches_the_planner(
        self, api: TestClient, cookies_for: dict, plan_id: str
    ) -> None:
        cookies_for.act_as("planner")
        entry = api.get(f"/api/plans/{plan_id}").json()["days"][0]["entries"][0]["id"]
        with api.websocket_connect(f"/api/ws/plans/{plan_id}") as socket:
            cookies_for.act_as("follower")
            api.put(
                f"/api/plans/{plan_id}/entries/{entry}/feedback",
                json={"rating": "liked"},
            )
            message = socket.receive_json()
        assert message["changed"] == ["feedback"]

    def test_a_check_off_broadcasts(self, api: TestClient, cookies_for: dict, plan_id: str) -> None:
        cookies_for.act_as("planner")
        with api.websocket_connect(f"/api/ws/plans/{plan_id}") as socket:
            cookies_for.act_as("follower")
            api.patch(f"/api/plans/{plan_id}/shopping-list/banana", json={"checked": True})
            message = socket.receive_json()
        assert message["changed"] == ["shopping_list"]

    def test_two_subscribers_both_receive(
        self, api: TestClient, cookies_for: dict, plan_id: str
    ) -> None:
        cookies_for.act_as("follower")
        with (
            api.websocket_connect(f"/api/ws/plans/{plan_id}") as first,
            api.websocket_connect(f"/api/ws/plans/{plan_id}") as second,
        ):
            cookies_for.act_as("planner")
            api.put(f"/api/plans/{plan_id}/days/6", json={"notes": "z"})
            assert first.receive_json()["type"] == "invalidate"
            assert second.receive_json()["type"] == "invalidate"

    def test_a_subscriber_on_another_plan_receives_nothing(
        self, api: TestClient, cookies_for: dict, plan_id: str
    ) -> None:
        cookies_for.act_as("planner")
        other = api.post("/api/plans", json={"name": "Другая", "start_date": "2026-12-21"}).json()[
            "id"
        ]
        with api.websocket_connect(f"/api/ws/plans/{other}") as socket:
            api.put(f"/api/plans/{plan_id}/days/6", json={"notes": "elsewhere"})
            api.put(f"/api/plans/{other}/days/0", json={"notes": "here"})
            # The first message must be this plan's: the other plan's change
            # must not have been delivered here at all.
            message = socket.receive_json()
        assert message["plan_id"] == other


class TestHubHousekeeping:
    @pytest.mark.anyio
    async def test_a_closed_socket_does_not_break_a_broadcast(self) -> None:
        """A client leaving mid-broadcast is ordinary, not an error.

        Letting it raise would abort delivery to everyone after it in the set.
        """
        from ration.api.ws import PlanHub

        class Dead:
            async def send_json(self, _message: dict) -> None:
                raise RuntimeError("socket closed")

        class Alive:
            def __init__(self) -> None:
                self.received: list[dict] = []

            async def send_json(self, message: dict) -> None:
                self.received.append(message)

        hub = PlanHub()
        dead, alive = Dead(), Alive()
        await hub.subscribe("p", dead)  # type: ignore[arg-type]
        await hub.subscribe("p", alive)  # type: ignore[arg-type]

        await hub.broadcast("p", ["entries"])

        assert alive.received, "a live subscriber missed the message"
        assert hub.subscriber_count("p") == 1, "the dead socket was not dropped"

    @pytest.mark.anyio
    async def test_unsubscribing_removes_the_plan_when_empty(self) -> None:
        from ration.api.ws import PlanHub

        class Socket:
            async def send_json(self, message: dict) -> None: ...

        hub = PlanHub()
        socket = Socket()
        await hub.subscribe("p", socket)  # type: ignore[arg-type]
        await hub.unsubscribe("p", socket)  # type: ignore[arg-type]
        assert hub.subscriber_count("p") == 0
