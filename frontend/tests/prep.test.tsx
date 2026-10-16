import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PrepPlan, formatDays } from "../src/features/planner/PrepPlan";
import { SessionProvider } from "../src/lib/session";

/** The reference plan's turkey session, as the API actually returns it. */
const SESSIONS = [
  {
    module_id: "lunch_rice_noodles_turkey",
    module_name: "Рисовая лапша с индейкой",
    portions: 3,
    day_indexes: [0, 1, 2],
    prep_notes: "Разложить по контейнерам сразу",
    items: [
      {
        ingredient_id: "turkey_thigh",
        name: "Бедро индейки",
        grams_raw: "553.8",
        grams_cooked_per_portion: "120",
      },
      {
        ingredient_id: "rice_noodles",
        name: "Рисовая лапша",
        grams_raw: "180",
        grams_cooked_per_portion: "170",
      },
    ],
  },
];

function mockApi(sessions: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = String(url).includes("/auth/me")
        ? { id: "u", display_name: "П", role: "planner", profile_id: "pr", locale: "ru" }
        : sessions;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderWithProviders(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SessionProvider>{ui}</SessionProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("formatDays", () => {
  it("is 1-based, matching the plan board rather than the array index", () => {
    expect(formatDays([0])).toBe("День 1");
  });

  it("collapses a consecutive run, which is the usual batch shape", () => {
    expect(formatDays([0, 1, 2])).toBe("Дни 1–3");
  });

  it("keeps a gap visible rather than implying a range", () => {
    expect(formatDays([0, 2])).toBe("Дни 1, 3");
  });

  it("handles runs and gaps together", () => {
    expect(formatDays([0, 1, 4])).toBe("Дни 1–2, 5");
  });

  it("does not depend on the order the API happens to send", () => {
    expect(formatDays([2, 0, 1])).toBe("Дни 1–3");
  });
});

describe("the prep plan screen", () => {
  it("shows the session with its portions and days", async () => {
    mockApi(SESSIONS);
    renderWithProviders(<PrepPlan planId="p1" />);

    expect(await screen.findByText("Рисовая лапша с индейкой")).toBeInTheDocument();
    expect(screen.getByText(/3 порции/)).toBeInTheDocument();
    expect(screen.getByText(/Дни 1–3/)).toBeInTheDocument();
    expect(screen.getByText("Разложить по контейнерам сразу")).toBeInTheDocument();
  });

  it("shows raw and per-container weights as two separate figures", async () => {
    // The whole point of the screen. 553.8 g of raw turkey becomes 120 g in
    // each of three boxes; a reader who confuses them packs four times too
    // much into the first container.
    mockApi(SESSIONS);
    renderWithProviders(<PrepPlan planId="p1" />);

    const row = (await screen.findByText("Бедро индейки")).closest("tr");
    expect(row).not.toBeNull();
    const cells = within(row!).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("553.8 г");
    expect(cells[2]).toHaveTextContent("120 г");
  });

  it("renders decimals exactly as sent, without re-rounding them", async () => {
    mockApi(SESSIONS);
    renderWithProviders(<PrepPlan planId="p1" />);
    // "553.8", not "554" and not "553.80". These numbers end up on a scale.
    expect(await screen.findByText("553.8 г")).toBeInTheDocument();
  });

  it("says so when the plan has nothing cooked in batches", async () => {
    mockApi([]);
    renderWithProviders(<PrepPlan planId="p1" />);
    expect(
      await screen.findByText("В этом плане нет блюд, которые готовятся партией"),
    ).toBeInTheDocument();
  });
});
