/**
 * The planner's two data screens, at the moment a reader first meets them.
 *
 * Both failures these cover were visible on the deployed demo and invisible
 * to every layer of the test suite, because each screen was asked whether it
 * rendered rather than what it said.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ModuleEditor } from "../src/features/planner/ModuleEditor";
import { PlanBuilder } from "../src/features/planner/PlanBuilder";
import { SessionProvider } from "../src/lib/session";

vi.mock("../src/lib/usePlanSocket", () => ({ usePlanSocket: () => {} }));

const MODULES = [
  {
    id: "m1", name: "Porridge with berries", slot: "breakfast", role: "main",
    batch_portions: 1, tags: [], prep_notes: null, kcal: "412", protein_g: "28.4",
    lines: [{ ingredient_id: "oats", grams_cooked: "250", size_is_critical: false }],
  },
  {
    id: "m2", name: "Chicken roll", slot: "lunch", role: "main",
    batch_portions: 3, tags: [], prep_notes: null, kcal: "530", protein_g: "41",
    lines: [{ ingredient_id: "chicken", grams_cooked: "180", size_is_critical: false }],
  },
];

const INGREDIENTS = [
  {
    id: "oats", names: { en: "Oats" }, kcal_per_100g: "350", protein_per_100g: "12",
    yield_factor: "1", yield_source: "as_purchased", shop_section: "grains",
    package_size: null, package_unit: null, aliases: [],
  },
];

/** Six days planned, a seventh left empty the way the reference week is. */
const PLAN = {
  id: "p1", name: "Pilot week 1", profile_id: "pr", start_date: "2026-10-12",
  status: "active",
  days: [...Array(7)].map((_, index) => ({
    day_index: index,
    date: `2026-10-${12 + index}`,
    day_template: "normal",
    notes: null,
    kcal: index === 6 ? "0" : "1702.4",
    protein_g: index === 6 ? "0" : "128.404",
    slot_totals: [],
    entries:
      index === 6
        ? []
        : [
            {
              id: `e${index}`, slot: "breakfast", module_id: "m1",
              module_name: "Porridge with berries", role: "main",
              portion_factor: "1.0", position: 0, kcal: "412", protein_g: "28.4",
              feedback: null,
            },
          ],
  })),
};

const PROFILE = {
  id: "pr", name: "Reference profile", locale: "en",
  daily_kcal_target: "1700", daily_kcal_tolerance: "50",
  daily_protein_min: "105", daily_protein_target: "110",
  slot_budgets: [], excluded_ingredients: [], caution_ingredients: [],
  frequency_rules: [], template_gates: [],
};

/** Routed by path, because these screens read several endpoints at once. */
function mockApi(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = String(url);
      const json = (body: unknown) =>
        new Response(JSON.stringify(body), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      if (path.includes("/auth/me")) {
        return json({
          id: "u", display_name: "Planner", role: "planner",
          profile_id: "pr", locale: "en",
        });
      }
      if (path.includes("/modules")) return json(MODULES);
      if (path.includes("/ingredients")) return json(INGREDIENTS);
      if (path.includes("/profiles")) return json(PROFILE);
      if (path.includes("/validation")) {
        return json({ findings: [], error_count: 0, warning_count: 0 });
      }
      if (path.includes("/plans/")) return json(PLAN);
      return json({});
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ModuleEditor", () => {
  it("opens on an invitation, not on an error about a form nobody filled in", async () => {
    mockApi();
    renderWithProviders(<ModuleEditor />);
    expect(
      await screen.findByText("Select a module on the left, or create a new one"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Add at least one ingredient")).not.toBeInTheDocument();
  });

  it("states the rule as a hint until the planner tries to save", async () => {
    mockApi();
    const user = userEvent.setup();
    renderWithProviders(<ModuleEditor />);
    await user.click(await screen.findByRole("button", { name: "New" }));

    // Present, so the requirement is known in advance — but not an alert,
    // because nothing has gone wrong yet.
    const hint = screen.getByText("Add at least one ingredient");
    expect(hint).toBeInTheDocument();
    expect(hint).not.toHaveAttribute("role", "alert");

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Add at least one ingredient");
  });

  it("filters the list by name and by meal", async () => {
    mockApi();
    const user = userEvent.setup();
    renderWithProviders(<ModuleEditor />);
    await screen.findByText("Porridge with berries");

    await user.type(screen.getByLabelText("Search by name"), "chicken");
    expect(screen.queryByText("Porridge with berries")).not.toBeInTheDocument();
    expect(screen.getByText("Chicken roll")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Search by name"));
    await user.selectOptions(screen.getByLabelText("All meals"), "breakfast");
    expect(screen.getByText("Porridge with berries")).toBeInTheDocument();
    expect(screen.queryByText("Chicken roll")).not.toBeInTheDocument();
  });
});

describe("PlanBuilder", () => {
  it("counts the days that are planned rather than implying seven are", async () => {
    mockApi();
    renderWithProviders(<PlanBuilder planId="p1" />);
    expect(await screen.findByText("6 of 7 days planned")).toBeInTheDocument();
  });

  it("calls the seventh day unplanned instead of reporting it as zero", async () => {
    mockApi();
    renderWithProviders(<PlanBuilder planId="p1" />);
    expect(await screen.findByText("Not planned")).toBeInTheDocument();
    // The failure being guarded: "0 kcal / 1,700 ± 50" reads as a day that
    // came out wrong, not a day nobody has written yet.
    expect(screen.queryByText(/^0 kcal/)).not.toBeInTheDocument();
  });

  it("rounds a planned day's totals for a reader", async () => {
    mockApi();
    renderWithProviders(<PlanBuilder planId="p1" />);
    // Six planned days carry the same totals, so assert on one of them.
    const headers = await screen.findAllByText(/1,702 kcal/);
    expect(headers).toHaveLength(6);
    expect(headers[0]).toHaveTextContent("128.4 g protein");
    // 1702.4 and 128.404 as stored; neither reaches the screen that way.
    expect(screen.queryByText(/1702\.4|128\.404/)).not.toBeInTheDocument();
  });
});
