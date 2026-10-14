import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShoppingList } from "../src/features/follower/ShoppingList";
import { SessionProvider } from "../src/lib/session";

const LIST = {
  plan_id: "p1",
  lines: [
    {
      ingredient_id: "turkey_thigh", name: "Бедро индейки", shop_section: "meat_fish",
      needed_raw_g: "553.8", purchase_amount: "553.8", overage_g: "0",
      packages: null, package_unit: null, checked: false,
      size_is_critical: false, is_staple: false,
    },
    {
      ingredient_id: "tortilla_wholegrain", name: "Цельнозерновая лепешка",
      shop_section: "grains", needed_raw_g: "225", purchase_amount: "225",
      overage_g: "0", packages: 3, package_unit: "pcs", checked: false,
      size_is_critical: true, is_staple: false,
    },
    {
      ingredient_id: "olive_oil", name: "Оливковое масло", shop_section: "oils_sauces",
      needed_raw_g: "20", purchase_amount: "20", overage_g: "0",
      packages: null, package_unit: null, checked: false,
      size_is_critical: false, is_staple: true,
    },
  ],
};

/**
 * A stateful mock: a PATCH updates what the next GET returns.
 *
 * A static mock would make the optimistic-update test pass for the wrong
 * reason — or fail for one, since the refetch after onSettled would revert the
 * tick the server had actually accepted.
 */
function mockApi(list: typeof LIST): void {
  const state = structuredClone(list);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/auth/me")) {
        return new Response(
          JSON.stringify({
            id: "u", display_name: "П", role: "follower", profile_id: "pr", locale: "ru",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (init?.method === "PATCH") {
        const id = String(url).split("/").pop()!;
        const { checked } = JSON.parse(init.body as string) as { checked: boolean };
        const line = state.lines.find((item) => item.ingredient_id === id);
        if (line) line.checked = checked;
        return new Response(JSON.stringify(line), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify(state), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderWithProviders(ui: ReactElement) {
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

describe("ShoppingList", () => {
  it("groups lines by shop section", async () => {
    mockApi(LIST);
    renderWithProviders(<ShoppingList planId="p1" />);
    expect(
      await screen.findByText("Мясо, рыба и морепродукты"),
    ).toBeInTheDocument();
    expect(screen.getByText("Крупы, лапша и хлеб")).toBeInTheDocument();
  });

  it("shows a piece count rather than grams for items sold by the item", async () => {
    mockApi(LIST);
    renderWithProviders(<ShoppingList planId="p1" />);
    expect(await screen.findByText("3 шт")).toBeInTheDocument();
  });

  it("calls out a critical size, because that was the pilot's real failure", async () => {
    mockApi(LIST);
    renderWithProviders(<ShoppingList planId="p1" />);
    expect(await screen.findByText("Важен размер")).toBeInTheDocument();
  });

  it("collapses staples, whose quantities are advisory", async () => {
    mockApi(LIST);
    renderWithProviders(<ShoppingList planId="p1" />);
    await screen.findByText("Мясо, рыба и морепродукты");
    expect(screen.queryByText("Оливковое масло")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Запасы/ }),
    );
    expect(screen.getByText("Оливковое масло")).toBeInTheDocument();
  });

  it("counts progress over real items, excluding staples", async () => {
    mockApi(LIST);
    renderWithProviders(<ShoppingList planId="p1" />);
    // Two non-staple lines, none checked.
    expect(await screen.findByText("0 из 2")).toBeInTheDocument();
  });

  it("ticks an item off and keeps it ticked after the refetch", async () => {
    mockApi(LIST);
    renderWithProviders(<ShoppingList planId="p1" />);
    const line = await screen.findByRole("button", { name: /Бедро индейки/ });

    await userEvent.click(line);
    await waitFor(() => expect(line).toHaveAttribute("aria-pressed", "true"));
    await waitFor(() => expect(screen.getByText("1 из 2")).toBeInTheDocument());
  });

  it("rolls back when the write fails", async () => {
    // A shop has bad signal; an optimistic tick that survives a failure would
    // tell the follower they had bought something they had not.
    mockApi(LIST);
    renderWithProviders(<ShoppingList planId="p1" />);
    const line = await screen.findByRole("button", { name: /Бедро индейки/ });

    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === "PATCH") {
          return new Response(
            JSON.stringify({ error: { code: "BOOM", message: "offline" } }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(JSON.stringify(LIST), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }),
    );

    await userEvent.click(line);
    await waitFor(() => expect(line).toHaveAttribute("aria-pressed", "false"));
  });

  it("gives every line a tappable target", async () => {
    mockApi(LIST);
    renderWithProviders(<ShoppingList planId="p1" />);
    const line = await screen.findByRole("button", { name: /Бедро индейки/ });
    expect(line.className).toContain("min-h-(--spacing-tap)");
  });
});
