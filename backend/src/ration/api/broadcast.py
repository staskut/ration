"""Fire an invalidation after a mutation, without blocking the response.

Broadcasts are **queued during the handler and dispatched after the commit**.
That ordering is the whole point of the two-step: the write is committed by
``get_session``'s teardown, which runs *after* the handler returns, so a
message sent from inside the handler reaches the other client while the
transaction is still open. That client refetches, its own session reads the
pre-commit database, and it renders stale data — permanently, because nothing
will tell it again. It is a race, so it fails perhaps half the time, and only
with two real clients against a real database.

The subtlety that makes this module exist: FastAPI runs a **synchronous**
handler in a threadpool worker, and that worker has no running event loop. A
naive ``asyncio.get_running_loop()`` there raises, and wrapping it in a
``suppress`` turns every broadcast into a silent no-op that no request-level
test can see. So the loop is captured at startup and the coroutine is submitted
to it across the thread boundary.

A failed broadcast must never fail the write that caused it: the data is
already committed, and a client that misses a message refetches on its next
interaction. But failing *silently and always* is a different thing, which is
why `test_an_entry_change_reaches_a_subscriber` exists.
"""

from __future__ import annotations

import asyncio
import contextlib
from concurrent.futures import Future

from fastapi import Request

from ration.api.ws import Changed

# asyncio holds only a weak reference to a running task, so a fire-and-forget
# one can be collected mid-flight and never deliver.
_pending: set[Future[None]] = set()


def notify(request: Request, plan_id: str, changed: list[Changed]) -> None:
    """Queue an invalidation. Delivered by :func:`dispatch_pending`, after the
    commit — never from here, see the module docstring."""
    if request is None:  # pragma: no cover - only if a handler omits Request
        return
    pending: dict[str, list[Changed]] = getattr(request.state, "broadcasts", None) or {}
    merged = pending.setdefault(plan_id, [])
    # Two mutations in one request may name overlapping resources; the client
    # gains nothing from being told twice.
    merged.extend(resource for resource in changed if resource not in merged)
    request.state.broadcasts = pending


def dispatch_pending(request: Request) -> None:
    """Send what the handler queued. Called once the write is durable.

    Never raises: a failed broadcast must not fail a write that has already
    committed. A client that misses a message refetches on its next
    interaction, and catches up on its next socket open.
    """
    pending: dict[str, list[Changed]] = getattr(request.state, "broadcasts", None) or {}
    if not pending:
        return
    request.state.broadcasts = {}
    for plan_id, changed in pending.items():
        _send(request, plan_id, changed)


def _send(request: Request, plan_id: str, changed: list[Changed]) -> None:
    hub = getattr(request.app.state, "plan_hub", None)
    loop = getattr(request.app.state, "event_loop", None)
    if hub is None or loop is None:
        return

    coroutine = hub.broadcast(plan_id, changed)
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is loop:
        # An async handler: schedule on the loop we are already on.
        task = loop.create_task(coroutine)
        _pending.add(task)  # type: ignore[arg-type]
        task.add_done_callback(_pending.discard)  # type: ignore[arg-type]
        return

    # A sync handler in a worker thread. This is the ordinary path.
    with contextlib.suppress(RuntimeError):
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        _pending.add(future)
        future.add_done_callback(_pending.discard)
