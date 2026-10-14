"""Per-plan invalidation broadcast.

Messages carry no payload (HLD AD-6). A subscriber is told *what changed*, not
what it changed to, and refetches. That keeps the response shapes in exactly one
place — the REST endpoints — instead of maintaining a second copy over the
socket that would drift.

The hub is in-process. A multi-process deployment would need a broker; see the
note on `PlanHub` before scaling out.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from ration.api.security import SessionCodec
from ration.config import SESSION_COOKIE_NAME, settings
from ration.repositories import models

Changed = Literal["entries", "validation", "shopping_list", "feedback", "days"]

router = APIRouter()


@dataclass
class PlanHub:
    """Subscribers grouped by plan.

    In-process only. With more than one worker each would hold its own
    subscribers and a change on one would never reach the other, so going
    multi-process means putting a broker behind this interface rather than
    adding workers and hoping.
    """

    _subscribers: dict[str, set[WebSocket]] = field(default_factory=lambda: defaultdict(set))
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def subscribe(self, plan_id: str, socket: WebSocket) -> None:
        async with self._lock:
            self._subscribers[plan_id].add(socket)

    async def unsubscribe(self, plan_id: str, socket: WebSocket) -> None:
        async with self._lock:
            self._subscribers[plan_id].discard(socket)
            if not self._subscribers[plan_id]:
                self._subscribers.pop(plan_id, None)

    async def broadcast(self, plan_id: str, changed: list[Changed]) -> None:
        """Tell everyone watching this plan what to refetch.

        A socket that has gone away is dropped rather than raising: a client
        closing mid-broadcast is ordinary, not an error, and letting it
        propagate would abort delivery to everyone after it in the set.
        """
        async with self._lock:
            targets = list(self._subscribers.get(plan_id, ()))

        message = {"type": "invalidate", "plan_id": plan_id, "changed": changed}
        dead = []
        for socket in targets:
            try:
                await socket.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                dead.append(socket)
        for socket in dead:
            await self.unsubscribe(plan_id, socket)

    def subscriber_count(self, plan_id: str) -> int:
        return len(self._subscribers.get(plan_id, ()))


def authorise(socket: WebSocket, plan_id: str, session: Session) -> bool:
    """A socket is authorised exactly as a request would be.

    A plan belonging to another profile is refused the same way a 404 refuses
    it: without confirming the plan exists.
    """
    token = socket.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return False
    user_id = SessionCodec(settings()).read(token)
    if user_id is None:
        return False

    user = session.get(models.User, user_id)
    if user is None:
        return False

    plan = session.get(models.Plan, plan_id)
    if plan is None:
        return False

    profile = session.scalars(
        select(models.Profile).where(
            (models.Profile.planner_user_id == user.id)
            | (models.Profile.follower_user_id == user.id)
        )
    ).first()
    return profile is not None and plan.profile_id == profile.id


@router.websocket("/ws/plans/{plan_id}")
async def plan_socket(socket: WebSocket, plan_id: str) -> None:
    app = socket.app
    with app.state.session_factory() as session:
        allowed = authorise(socket, plan_id, session)

    if not allowed:
        await socket.close(code=4403)
        return

    hub: PlanHub = app.state.plan_hub
    await socket.accept()
    await hub.subscribe(plan_id, socket)
    try:
        while True:
            # Nothing is expected from the client; this keeps the connection
            # open and notices a disconnect.
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        with contextlib.suppress(Exception):
            await hub.unsubscribe(plan_id, socket)
