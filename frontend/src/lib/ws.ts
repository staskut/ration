/**
 * Socket to query-cache invalidation.
 *
 * The message carries no payload, so this never patches the cache from it —
 * it invalidates and lets the query layer refetch. Patching would mean a
 * second copy of every response shape living in the socket handler, which is
 * the duplication HLD AD-6 exists to avoid.
 *
 * The app must work with the socket unavailable. A dropped connection
 * degrades to manual refresh; it does not break a screen.
 */
import type { QueryClient } from "@tanstack/react-query";

import { INVALIDATES, type ChangedResource } from "./queries";

interface InvalidateMessage {
  type: "invalidate";
  plan_id: string;
  changed: ChangedResource[];
}

const INITIAL_DELAY_MS = 500;
const MAX_DELAY_MS = 30_000;

/** Exponential backoff with jitter, so many clients do not reconnect in step. */
export function nextDelay(attempt: number): number {
  const base = Math.min(INITIAL_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
  return Math.round(base / 2 + Math.random() * (base / 2));
}

export function applyMessage(queryClient: QueryClient, raw: unknown): boolean {
  const message = raw as Partial<InvalidateMessage> | null;
  if (!message || message.type !== "invalidate" || !message.plan_id) return false;

  let applied = false;
  for (const resource of message.changed ?? []) {
    const invalidate = INVALIDATES[resource];
    if (!invalidate) continue; // A resource this client does not know about.
    for (const key of invalidate(message.plan_id)) {
      void queryClient.invalidateQueries({ queryKey: key });
      applied = true;
    }
  }
  return applied;
}

export interface Subscription {
  close: () => void;
}

export function subscribeToPlan(
  queryClient: QueryClient,
  planId: string,
  options: { url?: (id: string) => string; schedule?: typeof setTimeout } = {},
): Subscription {
  const buildUrl =
    options.url ??
    ((id: string) => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      return `${protocol}//${window.location.host}/api/ws/plans/${id}`;
    });
  const schedule = options.schedule ?? setTimeout;

  let socket: WebSocket | null = null;
  let attempt = 0;
  let closed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const connect = (): void => {
    if (closed) return;
    socket = new WebSocket(buildUrl(planId));

    socket.onopen = () => {
      // Catch up on every open, not only on a retry. Messages are
      // fire-and-forget: anything broadcast before this socket existed was
      // never queued for it, so a client that connects a moment late would
      // otherwise show stale data indefinitely. That is not hypothetical —
      // it is what made the end-to-end collaboration test flaky.
      void queryClient.invalidateQueries({ queryKey: ["plan", planId] });
      void queryClient.invalidateQueries({ queryKey: ["today"] });
      attempt = 0;
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        applyMessage(queryClient, JSON.parse(event.data));
      } catch {
        // A malformed frame is not worth tearing the connection down for.
      }
    };

    socket.onclose = () => {
      if (closed) return;
      timer = schedule(connect, nextDelay(attempt));
      attempt += 1;
    };
  };

  connect();

  return {
    close: () => {
      closed = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    },
  };
}
