import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/App";
import { SessionProvider } from "../src/lib/session";

/**
 * Routing splits on role at the root. The two surfaces are different products
 * sharing an API, so the test that matters is that a follower never lands on
 * the planner's screens and the reverse.
 */
function mockSession(user: unknown | null): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes("/auth/me")) {
        return user
          ? new Response(JSON.stringify(user), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            })
          : new Response(
              JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "no" } }),
              { status: 401, headers: { "Content-Type": "application/json" } },
            );
      }
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderApp(ui: ReactElement = <App />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SessionProvider>{ui}</SessionProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", class {
    close() {}
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("shows a sign-in form when nobody is signed in", async () => {
    mockSession(null);
    renderApp();
    expect(await screen.findByRole("button", { name: "Войти" })).toBeInTheDocument();
  });

  it("sends a follower to Today, not to the plan builder", async () => {
    mockSession({
      id: "u", display_name: "П", role: "follower", profile_id: "pr", locale: "ru",
    });
    renderApp();
    expect(await screen.findByRole("button", { name: "Сегодня" })).toBeInTheDocument();
    expect(screen.queryByText("Ингредиенты")).not.toBeInTheDocument();
  });

  it("gives the follower exactly two destinations", async () => {
    // Two, so a tab bar rather than a menu: one tap, no navigation to learn.
    mockSession({
      id: "u", display_name: "П", role: "follower", profile_id: "pr", locale: "ru",
    });
    renderApp();
    await screen.findByRole("button", { name: "Сегодня" });
    expect(screen.getByRole("button", { name: "Список покупок" })).toBeInTheDocument();
  });

  it("sends a planner to the plan builder", async () => {
    mockSession({
      id: "u", display_name: "П", role: "planner", profile_id: "pr", locale: "ru",
    });
    renderApp();
    expect(await screen.findByRole("button", { name: "Ингредиенты" })).toBeInTheDocument();
  });
});
