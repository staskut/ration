import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IngredientForm, yieldError } from "../src/features/planner/IngredientForm";
import { ValidationPanel } from "../src/features/planner/ValidationPanel";
import { SessionProvider } from "../src/lib/session";

const REPORT = {
  error_count: 1,
  warning_count: 1,
  findings: [
    {
      level: "error",
      code: "DAY_KCAL_OUT_OF_RANGE",
      message_key: "validation.day_kcal_out_of_range",
      params: { actual: "1577.6", min: "1650.0", max: "1750.0" },
      day_index: 0,
      slot: null,
      entry_id: null,
    },
    {
      level: "warning",
      code: "SLOT_OUT_OF_BUDGET",
      message_key: "validation.slot_kcal_out_of_budget",
      params: { actual: "380", min: "395", max: "420", metric: "kcal" },
      day_index: 0,
      slot: "breakfast",
      entry_id: null,
    },
  ],
};

function mockApi(body: unknown, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      String(url).includes("/auth/me")
        ? new Response(
            JSON.stringify({
              id: "u", display_name: "П", role: "planner", profile_id: "pr", locale: "ru",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          )
        : new Response(JSON.stringify(body), {
            status, headers: { "Content-Type": "application/json" },
          }),
    ),
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

describe("yield factor validation", () => {
  it.each(["0", "-1", "5.1", "99", "abc", ""])("rejects %s", (value) => {
    expect(yieldError(value)).toBeDefined();
  });

  it.each(["0.65", "1", "2.85", "5"])("accepts %s", (value) => {
    expect(yieldError(value)).toBeUndefined();
  });

  it("mirrors the server's bound so the planner learns before submitting", () => {
    // The API rejects the same range with a 422 naming the field.
    expect(yieldError("5")).toBeUndefined();
    expect(yieldError("5.0001")).toBeDefined();
  });
});

describe("IngredientForm", () => {
  it("blocks submission while the yield factor is invalid", async () => {
    mockApi({});
    renderWithProviders(<IngredientForm onDone={() => {}} />);
    const field = screen.getByLabelText("Yield");
    await userEvent.clear(field);
    await userEvent.type(field, "9");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("sends decimals as strings, never as numbers", async () => {
    mockApi({ id: "x" });
    renderWithProviders(<IngredientForm onDone={() => {}} />);
    await userEvent.type(screen.getByLabelText("Name"), "Треска");
    await userEvent.type(screen.getByLabelText("kcal / 100 g"), "82");
    await userEvent.type(screen.getByLabelText("protein / 100 g"), "17.8");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === "POST",
      );
      expect(call).toBeDefined();
      const body = JSON.parse((call![1] as RequestInit).body as string);
      expect(typeof body.kcal_per_100g).toBe("string");
      expect(body.protein_per_100g).toBe("17.8");
    });
  });

  it("uses text inputs, because a number input would parse to a float", () => {
    mockApi({});
    renderWithProviders(<IngredientForm onDone={() => {}} />);
    expect(screen.getByLabelText("kcal / 100 g")).toHaveAttribute("type", "text");
  });
});

describe("ValidationPanel", () => {
  it("renders findings as sentences, not codes", async () => {
    mockApi(REPORT);
    renderWithProviders(<ValidationPanel planId="p1" />);
    expect(await screen.findByText(/День 1: 1[\s\u00a0]578 ккал/)).toBeInTheDocument();
  });

  it("translates the slot name", async () => {
    mockApi(REPORT);
    renderWithProviders(<ValidationPanel planId="p1" />);
    expect(await screen.findByText(/Завтрак/)).toBeInTheDocument();
  });

  it("shows error and warning counts", async () => {
    mockApi(REPORT);
    renderWithProviders(<ValidationPanel planId="p1" />);
    expect(await screen.findByText(/Ошибок: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Предупреждений: 1/)).toBeInTheDocument();
  });

  it("shows an explicit clean state rather than a blank panel", async () => {
    mockApi({ findings: [], error_count: 0, warning_count: 0 });
    renderWithProviders(<ValidationPanel planId="p1" />);
    expect(await screen.findByText("Нарушений нет")).toBeInTheDocument();
  });

  it("calls back with the day when a finding is clicked", async () => {
    // Previously the button called a handler nobody passed, so it looked
    // interactive and did nothing.
    mockApi(REPORT);
    const onSelect = vi.fn();
    renderWithProviders(<ValidationPanel planId="p1" onSelect={onSelect} />);
    await userEvent.click(await screen.findByText(/День 1: 1[\s\u00a0]578 ккал/));
    expect(onSelect).toHaveBeenCalledWith(0);
  });
});
