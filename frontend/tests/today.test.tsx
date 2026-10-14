import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Today } from "../src/features/follower/Today";
import { SessionProvider } from "../src/lib/session";

const TODAY = {
  plan_id: "p1",
  date: "2026-10-12",
  day_index: 0,
  day_template: "long_shift",
  kcal: "1577.59",
  protein_g: "118.2",
  slots: [
    { slot: "breakfast", time: "06:00", kcal: "0", protein_g: "0", entries: [] },
    {
      slot: "dinner",
      time: "21:00",
      kcal: "480",
      protein_g: "40",
      entries: [
        {
          entry_id: "e1",
          module_id: "dinner_fish",
          module_name: "Белая рыба с тыквой",
          portion_grams: "510",
          kcal: "480",
          protein_g: "40",
          home_only: true,
          critical_notes: ["Цельнозерновая лепешка: 75 г"],
          feedback: { plan_entry_id: "e1", status: "tried", rating: "liked" },
        },
      ],
    },
  ],
};

function mockApi(body: unknown, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes("/auth/me")) {
        return new Response(
          JSON.stringify({
            id: "u",
            display_name: "Подопечный",
            role: "follower",
            profile_id: "pr",
            locale: "ru",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
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

describe("Today", () => {
  it("shows the slot time from the day's template, not a fixed one", async () => {
    // A long shift moves dinner to 21:00. Showing 18:00 would send the
    // follower home three hours early.
    mockApi(TODAY);
    renderWithProviders(<Today />);
    expect(await screen.findByText(/21:00/)).toBeInTheDocument();
  });

  it("renders the portion weight, so a container can be packed on a scale", async () => {
    mockApi(TODAY);
    renderWithProviders(<Today />);
    expect(await screen.findByText(/510 г/)).toBeInTheDocument();
  });

  it("marks a home-only meal", async () => {
    mockApi(TODAY);
    renderWithProviders(<Today />);
    expect(await screen.findByText("Дома")).toBeInTheDocument();
  });

  it("surfaces a critical size note", async () => {
    mockApi(TODAY);
    renderWithProviders(<Today />);
    expect(
      await screen.findByText(/Цельнозерновая лепешка: 75 г/),
    ).toBeInTheDocument();
  });

  it("renders numbers with the Russian decimal separator", async () => {
    mockApi(TODAY);
    renderWithProviders(<Today />);
    expect(await screen.findByText(/1577,59/)).toBeInTheDocument();
  });

  it("hides empty slots rather than listing five blank rows", async () => {
    mockApi(TODAY);
    renderWithProviders(<Today />);
    await screen.findByText(/21:00/);
    expect(screen.queryByText("06:00")).not.toBeInTheDocument();
  });

  it("shows a calm empty state on an unplanned day", async () => {
    mockApi({ ...TODAY, slots: TODAY.slots.map((s) => ({ ...s, entries: [] })) });
    renderWithProviders(<Today />);
    expect(
      await screen.findByText("На этот день ничего не запланировано"),
    ).toBeInTheDocument();
  });

  it("shows the existing rating without opening anything", async () => {
    mockApi(TODAY);
    renderWithProviders(<Today />);
    const liked = await screen.findByRole("button", { name: "Понравилось" });
    expect(liked).toHaveAttribute("aria-pressed", "true");
  });

  it("sends exactly one request when a rating is tapped", async () => {
    mockApi(TODAY);
    renderWithProviders(<Today />);
    const disliked = await screen.findByRole("button", { name: "Не понравилось" });

    const before = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.click(disliked);
    await waitFor(() => {
      const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
      const feedback = calls.filter((call) => String(call[0]).includes("/feedback"));
      expect(feedback).toHaveLength(1);
      expect(calls.length).toBeGreaterThan(before);
    });
  });

  it("never sends status — the server infers it", async () => {
    mockApi(TODAY);
    renderWithProviders(<Today />);
    await userEvent.click(await screen.findByRole("button", { name: "Нормально" }));
    await waitFor(() => {
      const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
        (c) => String(c[0]).includes("/feedback"),
      );
      expect(call).toBeDefined();
      expect(JSON.parse((call![1] as RequestInit).body as string)).toEqual({
        rating: "neutral",
      });
    });
  });
});
