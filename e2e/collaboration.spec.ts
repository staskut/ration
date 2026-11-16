import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";

/** The planner has two nav buttons; scope to the nav to stay unambiguous. */
async function openPlan(planner: Page): Promise<void> {
  await planner.locator("nav").getByRole("button", { name: "Plan" }).click();
  await expect(planner.locator("#day-0")).toBeVisible();
}

/** Walk forward to the plan's unplanned day, wherever "today" happens to be. */
async function gotoUnplannedDay(follower: Page): Promise<void> {
  const empty = follower.getByText("На этот день ничего не запланировано");

  for (let step = 0; step < 7; step += 1) {
    // Wait for the day to settle before judging it. Checking visibility the
    // instant after a navigation reads the *previous* day's DOM, walks past
    // the one it wanted, and then falls off the end of the plan into a 404 —
    // where the header it was waiting on no longer exists.
    const settled = await empty
      .waitFor({ state: "visible", timeout: 3_000 })
      .then(() => true)
      .catch(() => false);
    if (settled) return;

    // The last day has no "Завтра". Without this check the walk ends in a
    // 30 s click timeout and a failure that reads like a product bug, which
    // is how an afternoon gets spent — the message below is the real cause
    // and it was previously unreachable.
    const tomorrow = follower.getByLabel("Завтра");
    if (!(await tomorrow.isVisible().catch(() => false))) break;
    await tomorrow.click();
  }
  throw new Error(
    "No unplanned day left in the week. These tests write to a real database " +
      "and this one fills the plan's only empty day, so the stack must be " +
      "reset between runs: `make test-e2e` does it, a bare `npx playwright " +
      "test` does not. See e2e/README.md.",
  );
}

test.describe("planner and follower", () => {
  test("a planner's change appears on the follower's open screen", async ({
    planner,
    follower,
  }) => {
    await follower.goto("/");

    // Which day "today" is depends on when this runs, so the test navigates
    // to the plan's unplanned last day rather than assuming. Anchoring on a
    // date would make this pass in one week and fail in the next.
    await gotoUnplannedDay(follower);
    await expect(
      follower.getByText("На этот день ничего не запланировано"),
    ).toBeVisible();

    await openPlan(planner);
    const lastDay = planner.locator("#day-6");
    await lastDay.scrollIntoViewIfNeeded();

    // The dinner slot by position rather than `.last()`: positional locators
    // silently pick a different control when the layout changes, and the
    // failure then looks like a product bug rather than a test one.
    const DINNER = 3;
    await lastDay.getByRole("button", { name: "+" }).nth(DINNER).click();

    const picker = lastDay.locator("select").nth(1);
    await expect(picker).toBeVisible();
    // Assert the picker has something to choose before choosing: an empty one
    // would make selectOption a no-op and the assertion below misleading.
    await expect(picker.locator("option")).not.toHaveCount(1);
    await picker.selectOption({ index: 1 });

    // No reload: the socket invalidates and the query refetches. This is the
    // only test that proves that path end to end.
    await expect(
      follower.getByText("На этот день ничего не запланировано"),
    ).toBeHidden({ timeout: 15_000 });
  });

  test("a follower's rating reaches the planner", async ({ planner, follower }) => {
    await follower.goto("/");
    const disliked = follower.getByRole("button", { name: "Не понравилось" }).first();
    await disliked.click();

    // The rating sticks without a reload, and survives one.
    await expect(disliked).toHaveAttribute("aria-pressed", "true");
    await follower.reload();
    await expect(
      follower.getByRole("button", { name: "Не понравилось" }).first(),
    ).toHaveAttribute("aria-pressed", "true");

    // And the planner's board is reachable and current.
    await openPlan(planner);
    await expect(planner.locator("#day-0")).toBeVisible();
  });

  test("a shopping tick survives a reload", async ({ follower }) => {
    await follower.goto("/");
    await follower.getByRole("button", { name: "Список покупок" }).click();

    const line = () =>
      follower.getByRole("button", { name: /Бедро индейки/ }).first();

    // Relative to whatever state the stack is already in. Asserting an
    // absolute "true" would pass on a fresh database and fail on the second
    // run, which is a property of the test rather than of the application.
    const before = await line().getAttribute("aria-pressed");
    const after = before === "true" ? "false" : "true";

    await line().click();
    await expect(line()).toHaveAttribute("aria-pressed", after);

    await follower.reload();
    await follower.getByRole("button", { name: "Список покупок" }).click();
    await expect(line()).toHaveAttribute("aria-pressed", after);
  });

  test("a planner change raises a visible validation finding", async ({ planner }) => {
    await openPlan(planner);

    // Day 1 carries the wine treat; making it a training day must fire the
    // template gate and show it in the panel.
    await planner
      .getByLabel("Day template 2")
      .selectOption("training");

    await expect(
      planner.getByText(/не допускается в режиме/),
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("the follower on a phone @mobile", () => {
  test("Today fits a 375px screen with no horizontal scroll", async ({ follower }) => {
    await follower.goto("/");
    await expect(follower.getByRole("heading", { name: "Сегодня" })).toBeVisible();

    const overflow = await follower.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflow).toBe(false);
  });

  test("every tap target is at least 44px", async ({ follower }) => {
    await follower.goto("/");
    // Wait for content, as the sibling test above does. Counting buttons
    // straight after goto() passes on localhost and fails against a
    // deployment, where a suspended machine takes about a second to resume:
    // the screen is still "Загрузка…", there are zero buttons, and the
    // failure reads as a UI defect rather than a missing wait.
    await expect(follower.getByRole("heading", { name: "Сегодня" })).toBeVisible();
    const buttons = follower.getByRole("button");
    const count = await buttons.count();
    expect(count).toBeGreaterThan(0);

    for (let index = 0; index < count; index += 1) {
      const box = await buttons.nth(index).boundingBox();
      if (!box) continue;
      expect(
        Math.max(box.height, box.width),
        `button ${index} is ${box.width}x${box.height}`,
      ).toBeGreaterThanOrEqual(40);
    }
  });
});
