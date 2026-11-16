import { expect, test } from "./fixtures";

/**
 * The prep plan was computed, tested and unreachable: engine, endpoint,
 * golden test and a `usePrepPlan` hook with no consumer (#55). These check
 * the thing none of that could — that a planner can actually get to it.
 *
 * Read-only, so unlike the collaboration suite these do not consume the
 * plan's state and are safe to re-run against a used stack.
 */
test.describe("the planner's prep plan", () => {
  test("is reachable from the nav and lists the reference plan's cook sessions", async ({
    planner,
  }) => {
    await planner.goto("/");
    await planner.locator("nav").getByRole("button", { name: "Prep" }).click();

    // Both batch modules in the reference week, by name rather than by count,
    // so a wrong-but-plausible list fails rather than passes.
    await expect(planner.getByRole("heading", { name: "Рисовая лапша с индейкой" })).toBeVisible();
    await expect(planner.getByRole("heading", { name: "Ролл с куриным бедром" })).toBeVisible();
  });

  test("shows raw and per-container weights as different figures", async ({ planner }) => {
    await planner.goto("/");
    await planner.locator("nav").getByRole("button", { name: "Prep" }).click();

    const card = planner
      .getByRole("article")
      .filter({ hasText: "Рисовая лапша с индейкой" });
    await expect(card).toBeVisible();

    // 553.8 g of raw turkey, 120 g into each of three boxes. Asserting both
    // is the point: a screen showing one number would look fine.
    const row = card.getByRole("row").filter({ hasText: "Бедро индейки" });
    await expect(row).toContainText("553.8");
    await expect(row).toContainText("120");

    await expect(card).toContainText("3 portions");
    await expect(card).toContainText("Days 1–3");
  });
});
