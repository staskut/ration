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

// A Monday in the past, deliberately not today. QA caught the first version
// of this fixture dated today: "the tap lands on the plan's first day" then
// passed whether or not the button did anything, because the header already
// showed that date. A test that is vacuous on the day it is written and
// meaningful the day after is worse than one that simply fails.
const PLAN_START = "2026-11-02";
const PLAN_END = "2026-11-08";
const PLANS = [
  { id: "p1", name: "Пилотная неделя 1", profile_id: "pr", start_date: PLAN_START, status: "active" },
];

function mockApi(
  body: unknown,
  status = 200,
  plans: unknown = PLANS,
  plansStatus = 200,
): void {
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
      if (String(url).includes("/plans")) {
        return new Response(JSON.stringify(plans), {
          status: plansStatus,
          headers: { "Content-Type": "application/json" },
        });
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

function todayIsoForTest(): string {
  return new Date().toISOString().slice(0, 10);
}

describe("Today outside the plan's week", () => {
  // The bug these pin: the day navigation used to render only in the success
  // branch, so a date with no plan behind it produced an error screen with no
  // arrows — a dead end. Every date is outside the plan once its week has
  // passed, so the follower's own screen broke on the day the plan ran out and
  // the public demo sat like that for a month (#75).

  it("still offers the day navigation when the day has no plan", async () => {
    mockApi({ error: { code: "NOT_FOUND", message: "No plan covers this date" } }, 404);
    renderWithProviders(<Today />);

    expect(await screen.findByLabelText("Вчера")).toBeInTheDocument();
    expect(screen.getByLabelText("Завтра")).toBeInTheDocument();
  });

  it("says the day is outside the plan rather than that something went wrong", async () => {
    // A 404 here is not a failure. Calling it one sends the follower looking
    // for a fault that is not there.
    mockApi({ error: { code: "NOT_FOUND", message: "No plan covers this date" } }, 404);
    renderWithProviders(<Today />);

    expect(await screen.findByText(/вне плана/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("still reports a real failure as a failure", async () => {
    mockApi({ error: { code: "INTERNAL", message: "boom" } }, 500);
    renderWithProviders(<Today />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByLabelText("Завтра")).toBeInTheDocument();
  });

  it("navigates away from a day outside the plan", async () => {
    // QA caught this one asserting that a button was enabled while its comment
    // claimed it checked the date — a test weaker than it read. It now reads
    // the date out of the header and asserts it actually moved.
    mockApi({ error: { code: "NOT_FOUND", message: "No plan covers this date" } }, 404);
    renderWithProviders(<Today />);

    const before = (await screen.findByText(todayIsoForTest())).textContent;
    await userEvent.click(screen.getByLabelText("Завтра"));

    await waitFor(() => {
      expect(screen.queryByText(before ?? "")).not.toBeInTheDocument();
    });
  });

  it("names the plan's week and offers one tap into it", async () => {
    // Arrows alone leave the follower guessing which way and how far. For a
    // plan a fortnight behind that is fourteen blind taps, which is what QA
    // failed #75 on.
    mockApi({ error: { code: "NOT_FOUND", message: "No plan covers this date" } }, 404);
    renderWithProviders(<Today />);

    expect(
      await screen.findByText(`Неделя плана: ${PLAN_START} – ${PLAN_END}`),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Перейти к плану" })).toBeInTheDocument();
  });

  it("the tap lands on the plan's first day", async () => {
    mockApi({ error: { code: "NOT_FOUND", message: "No plan covers this date" } }, 404);
    renderWithProviders(<Today />);

    await userEvent.click(await screen.findByRole("button", { name: "Перейти к плану" }));

    // The header now shows the plan's own first day rather than the date the
    // screen opened on. Matched exactly: the week line below it contains the
    // same date inside a range, and a substring match would pass on that
    // without the header having moved at all. PLAN_START is a past Monday, so
    // this cannot pass by the header having been there all along.
    expect(await screen.findByText(PLAN_START, { exact: true })).toBeInTheDocument();
    expect(screen.queryByText(todayIsoForTest(), { exact: true })).not.toBeInTheDocument();
  });

  it("says the day is outside the plan when the plan list comes back empty", async () => {
    // The week and the button are an improvement on the message, not a
    // replacement for it: a follower with no plan to point at still gets told
    // where they are. Named for what it arranges — QA's note that the previous
    // name said "unavailable" while the mock returned an empty 200.
    mockApi({ error: { code: "NOT_FOUND", message: "No plan covers this date" } }, 404, []);
    renderWithProviders(<Today />);

    expect(await screen.findByText(/вне плана/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Завтра")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Перейти к плану" })).not.toBeInTheDocument();
  });

  it("says it too when the plan list itself fails", async () => {
    mockApi(
      { error: { code: "NOT_FOUND", message: "No plan covers this date" } },
      404,
      { error: { code: "INTERNAL", message: "boom" } },
      500,
    );
    renderWithProviders(<Today />);

    expect(await screen.findByText(/вне плана/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Завтра")).toBeInTheDocument();
  });
});
