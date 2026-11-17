import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/App";
import { SessionProvider } from "../src/lib/session";

/**
 * Routing splits on role at the root. The two surfaces are different products
 * sharing an API, so the test that matters is that a follower never lands on
 * the planner's screens and the reverse.
 */
function mockSession(user: unknown | null, demo?: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${String(url)}`);
      if (String(url).includes("/auth/demo")) {
        return new Response(JSON.stringify(demo ?? { available: false, roles: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
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

let calls: string[] = [];

beforeEach(() => {
  calls = [];
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
    // Nobody is signed in, so no profile locale has loaded: the sign-in form
    // renders in the fallback locale.
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("sends a follower to Today, not to the plan builder", async () => {
    mockSession({
      id: "u", display_name: "П", role: "follower", profile_id: "pr", locale: "ru",
    });
    renderApp();
    expect(await screen.findByRole("button", { name: "Сегодня" })).toBeInTheDocument();
    expect(screen.queryByText("Ingredients")).not.toBeInTheDocument();
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
    expect(await screen.findByRole("button", { name: "Ingredients" })).toBeInTheDocument();
  });
});

describe("the sign-in page", () => {
  it("says what the product is, rather than showing two bare fields", async () => {
    mockSession(null);
    renderApp();
    expect(
      await screen.findByText(
        "A weekly meal plan for two: one person builds it, the other eats it.",
      ),
    ).toBeInTheDocument();
  });

  it("labels both fields, so they are reachable by accessible name", async () => {
    // They were placeholders. A placeholder disappears as soon as there is a
    // value in the field, and it is not an accessible name — anything
    // navigating by label could not find either input.
    mockSession(null);
    renderApp();
    expect(await screen.findByLabelText("Email")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
  });

  it("offers one-click entry where the deployment is a demo", async () => {
    mockSession(null, { available: true, roles: ["planner", "follower"] });
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("button", { name: "Enter as the planner" }));
    await waitFor(() =>
      expect(calls.some((c) => c.startsWith("POST") && c.endsWith("/auth/demo"))).toBe(
        true,
      ),
    );
    expect(screen.getByText(/The demo's data is fictional/)).toBeInTheDocument();
  });

  it("offers no demo entry where there is none", async () => {
    // Production answers `available: false`, so the buttons never render
    // rather than rendering and failing.
    mockSession(null, { available: false, roles: [] });
    renderApp();
    await screen.findByRole("button", { name: "Sign in" });
    expect(
      screen.queryByRole("button", { name: "Enter as the planner" }),
    ).not.toBeInTheDocument();
  });
});

describe("the account bar", () => {
  it("names the person and their role, and offers a way out", async () => {
    mockSession({
      id: "u", display_name: "Reference planner", role: "planner",
      profile_id: "pr", locale: "en",
    });
    const user = userEvent.setup();
    renderApp();

    expect(await screen.findByText(/Reference planner/)).toBeInTheDocument();
    expect(screen.getByText(/Planner/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() =>
      expect(
        calls.some((c) => c.startsWith("POST") && c.endsWith("/auth/logout")),
      ).toBe(true),
    );
  });

  it("is on the follower's screens too", async () => {
    mockSession({
      id: "u", display_name: "Reference follower", role: "follower",
      profile_id: "pr", locale: "en",
    });
    renderApp();
    expect(await screen.findByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });
});
