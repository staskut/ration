import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { applyMessage, nextDelay, subscribeToPlan } from "../src/lib/ws";

function clientSpy() {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  return { client, invalidate };
}

describe("applying an invalidation message", () => {
  it("invalidates exactly the keys the resource maps to", () => {
    const { client, invalidate } = clientSpy();
    applyMessage(client, {
      type: "invalidate",
      plan_id: "p",
      changed: ["shopping_list"],
    });
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["plan", "p", "shopping-list"],
    });
  });

  it("invalidates the plan subtree for an entry change", () => {
    const { client, invalidate } = clientSpy();
    applyMessage(client, { type: "invalidate", plan_id: "p", changed: ["entries"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["plan", "p"] });
  });

  it("invalidates nothing for a resource it does not know", () => {
    // Forward compatibility: a server that learns a new resource must not make
    // an older client throw.
    const { client, invalidate } = clientSpy();
    const applied = applyMessage(client, {
      type: "invalidate",
      plan_id: "p",
      changed: ["something_new" as never],
    });
    expect(applied).toBe(false);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("ignores a message of the wrong type", () => {
    const { client, invalidate } = clientSpy();
    expect(applyMessage(client, { type: "hello", plan_id: "p" })).toBe(false);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("ignores a message with no plan", () => {
    const { client, invalidate } = clientSpy();
    expect(applyMessage(client, { type: "invalidate", changed: ["entries"] })).toBe(false);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("ignores null without throwing", () => {
    const { client } = clientSpy();
    expect(applyMessage(client, null)).toBe(false);
  });
});

describe("reconnect backoff", () => {
  it("grows with each attempt", () => {
    const first = nextDelay(0);
    const later = nextDelay(5);
    expect(later).toBeGreaterThan(first);
  });

  it("is capped, so a long outage does not become an hour-long wait", () => {
    expect(nextDelay(50)).toBeLessThanOrEqual(30_000);
  });

  it("is jittered, so many clients do not reconnect in step", () => {
    const samples = new Set(Array.from({ length: 30 }, () => nextDelay(4)));
    expect(samples.size).toBeGreaterThan(1);
  });

  it("is never zero or negative", () => {
    for (let attempt = 0; attempt < 12; attempt += 1) {
      expect(nextDelay(attempt)).toBeGreaterThan(0);
    }
  });
});

describe("catching up when the socket opens", () => {
  /** Minimal stand-in: the production code only ever sets the handlers. */
  class FakeSocket {
    static last: FakeSocket | null = null;
    onopen: (() => void) | null = null;
    onmessage: ((event: MessageEvent<string>) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    close = vi.fn();
    constructor() {
      FakeSocket.last = this;
    }
  }

  function subscribe() {
    const { client, invalidate } = clientSpy();
    vi.stubGlobal("WebSocket", FakeSocket);
    const subscription = subscribeToPlan(client, "plan-1", {
      url: (id) => `ws://test/${id}`,
    });
    return { invalidate, subscription };
  }

  it("refetches on the very first open, not only after a reconnect", () => {
    // Broadcasts are fire-and-forget and nothing is queued for a socket that
    // did not exist yet. A client connecting a moment after a change would
    // otherwise sit on stale data until something else refetched it — the
    // flake this guards against was exactly that.
    const { invalidate, subscription } = subscribe();
    expect(invalidate).not.toHaveBeenCalled();

    FakeSocket.last?.onopen?.();

    const keys = invalidate.mock.calls.map((call) =>
      JSON.stringify((call[0] as { queryKey: unknown }).queryKey),
    );
    expect(keys).toContain(JSON.stringify(["plan", "plan-1"]));
    subscription.close();
  });

  it("includes today, which is keyed by date and not under the plan prefix", () => {
    const { invalidate, subscription } = subscribe();
    FakeSocket.last?.onopen?.();

    const keys = invalidate.mock.calls.map((call) =>
      JSON.stringify((call[0] as { queryKey: unknown }).queryKey),
    );
    expect(keys).toContain(JSON.stringify(["today"]));
    subscription.close();
  });
});
