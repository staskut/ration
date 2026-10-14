"""Fire an invalidation after a mutation, without blocking the response.

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
