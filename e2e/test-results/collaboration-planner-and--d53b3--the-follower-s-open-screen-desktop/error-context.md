# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: collaboration.spec.ts >> planner and follower >> a planner's change appears on the follower's open screen
- Location: collaboration.spec.ts:43:3

# Error details

```
Error: expect(locator).toBeHidden() failed

Locator:  getByText('На этот день ничего не запланировано')
Expected: hidden
Received: visible
Timeout:  15000ms

Call log:
  - Expect "toBeHidden" getByText('На этот день ничего не запланировано') with timeout 15000ms
  - waiting for getByText('На этот день ничего не запланировано')
    34 × locator resolved to <p class="px-4 py-8 text-center text-slate-400">На этот день ничего не запланировано</p>
       - unexpected value "visible"

```

```yaml
- paragraph: На этот день ничего не запланировано
```

# Test source

```ts
  1   | import type { Page } from "@playwright/test";
  2   | 
  3   | import { expect, test } from "./fixtures";
  4   | 
  5   | /** The planner has two nav buttons; scope to the nav to stay unambiguous. */
  6   | async function openPlan(planner: Page): Promise<void> {
  7   |   await planner.locator("nav").getByRole("button", { name: "План" }).click();
  8   |   await expect(planner.locator("#day-0")).toBeVisible();
  9   | }
  10  | 
  11  | /** Walk forward to the plan's unplanned day, wherever "today" happens to be. */
  12  | async function gotoUnplannedDay(follower: Page): Promise<void> {
  13  |   const empty = follower.getByText("На этот день ничего не запланировано");
  14  | 
  15  |   for (let step = 0; step < 7; step += 1) {
  16  |     // Wait for the day to settle before judging it. Checking visibility the
  17  |     // instant after a navigation reads the *previous* day's DOM, walks past
  18  |     // the one it wanted, and then falls off the end of the plan into a 404 —
  19  |     // where the header it was waiting on no longer exists.
  20  |     const settled = await empty
  21  |       .waitFor({ state: "visible", timeout: 3_000 })
  22  |       .then(() => true)
  23  |       .catch(() => false);
  24  |     if (settled) return;
  25  | 
  26  |     // The last day has no "Завтра". Without this check the walk ends in a
  27  |     // 30 s click timeout and a failure that reads like a product bug, which
  28  |     // is how an afternoon gets spent — the message below is the real cause
  29  |     // and it was previously unreachable.
  30  |     const tomorrow = follower.getByLabel("Завтра");
  31  |     if (!(await tomorrow.isVisible().catch(() => false))) break;
  32  |     await tomorrow.click();
  33  |   }
  34  |   throw new Error(
  35  |     "No unplanned day left in the week. These tests write to a real database " +
  36  |       "and this one fills the plan's only empty day, so the stack must be " +
  37  |       "reset between runs: `make test-e2e` does it, a bare `npx playwright " +
  38  |       "test` does not. See e2e/README.md.",
  39  |   );
  40  | }
  41  | 
  42  | test.describe("planner and follower", () => {
  43  |   test("a planner's change appears on the follower's open screen", async ({
  44  |     planner,
  45  |     follower,
  46  |   }) => {
  47  |     await follower.goto("/");
  48  | 
  49  |     // Which day "today" is depends on when this runs, so the test navigates
  50  |     // to the plan's unplanned last day rather than assuming. Anchoring on a
  51  |     // date would make this pass in one week and fail in the next.
  52  |     await gotoUnplannedDay(follower);
  53  |     await expect(
  54  |       follower.getByText("На этот день ничего не запланировано"),
  55  |     ).toBeVisible();
  56  | 
  57  |     await openPlan(planner);
  58  |     const lastDay = planner.locator("#day-6");
  59  |     await lastDay.scrollIntoViewIfNeeded();
  60  | 
  61  |     // The dinner slot by position rather than `.last()`: positional locators
  62  |     // silently pick a different control when the layout changes, and the
  63  |     // failure then looks like a product bug rather than a test one.
  64  |     const DINNER = 3;
  65  |     await lastDay.getByRole("button", { name: "+" }).nth(DINNER).click();
  66  | 
  67  |     const picker = lastDay.locator("select").nth(1);
  68  |     await expect(picker).toBeVisible();
  69  |     // Assert the picker has something to choose before choosing: an empty one
  70  |     // would make selectOption a no-op and the assertion below misleading.
  71  |     await expect(picker.locator("option")).not.toHaveCount(1);
  72  |     await picker.selectOption({ index: 1 });
  73  | 
  74  |     // No reload: the socket invalidates and the query refetches. This is the
  75  |     // only test that proves that path end to end.
  76  |     await expect(
  77  |       follower.getByText("На этот день ничего не запланировано"),
> 78  |     ).toBeHidden({ timeout: 15_000 });
      |       ^ Error: expect(locator).toBeHidden() failed
  79  |   });
  80  | 
  81  |   test("a follower's rating reaches the planner", async ({ planner, follower }) => {
  82  |     await follower.goto("/");
  83  |     const disliked = follower.getByRole("button", { name: "Не понравилось" }).first();
  84  |     await disliked.click();
  85  | 
  86  |     // The rating sticks without a reload, and survives one.
  87  |     await expect(disliked).toHaveAttribute("aria-pressed", "true");
  88  |     await follower.reload();
  89  |     await expect(
  90  |       follower.getByRole("button", { name: "Не понравилось" }).first(),
  91  |     ).toHaveAttribute("aria-pressed", "true");
  92  | 
  93  |     // And the planner's board is reachable and current.
  94  |     await openPlan(planner);
  95  |     await expect(planner.locator("#day-0")).toBeVisible();
  96  |   });
  97  | 
  98  |   test("a shopping tick survives a reload", async ({ follower }) => {
  99  |     await follower.goto("/");
  100 |     await follower.getByRole("button", { name: "Список покупок" }).click();
  101 | 
  102 |     const line = () =>
  103 |       follower.getByRole("button", { name: /Бедро индейки/ }).first();
  104 | 
  105 |     // Relative to whatever state the stack is already in. Asserting an
  106 |     // absolute "true" would pass on a fresh database and fail on the second
  107 |     // run, which is a property of the test rather than of the application.
  108 |     const before = await line().getAttribute("aria-pressed");
  109 |     const after = before === "true" ? "false" : "true";
  110 | 
  111 |     await line().click();
  112 |     await expect(line()).toHaveAttribute("aria-pressed", after);
  113 | 
  114 |     await follower.reload();
  115 |     await follower.getByRole("button", { name: "Список покупок" }).click();
  116 |     await expect(line()).toHaveAttribute("aria-pressed", after);
  117 |   });
  118 | 
  119 |   test("a planner change raises a visible validation finding", async ({ planner }) => {
  120 |     await openPlan(planner);
  121 | 
  122 |     // Day 1 carries the wine treat; making it a training day must fire the
  123 |     // template gate and show it in the panel.
  124 |     await planner
  125 |       .getByLabel("Режим дня 2")
  126 |       .selectOption("training");
  127 | 
  128 |     await expect(
  129 |       planner.getByText(/не допускается в режиме/),
  130 |     ).toBeVisible({ timeout: 15_000 });
  131 |   });
  132 | });
  133 | 
  134 | test.describe("the follower on a phone @mobile", () => {
  135 |   test("Today fits a 375px screen with no horizontal scroll", async ({ follower }) => {
  136 |     await follower.goto("/");
  137 |     await expect(follower.getByRole("heading", { name: "Сегодня" })).toBeVisible();
  138 | 
  139 |     const overflow = await follower.evaluate(
  140 |       () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  141 |     );
  142 |     expect(overflow).toBe(false);
  143 |   });
  144 | 
  145 |   test("every tap target is at least 44px", async ({ follower }) => {
  146 |     await follower.goto("/");
  147 |     const buttons = follower.getByRole("button");
  148 |     const count = await buttons.count();
  149 |     expect(count).toBeGreaterThan(0);
  150 | 
  151 |     for (let index = 0; index < count; index += 1) {
  152 |       const box = await buttons.nth(index).boundingBox();
  153 |       if (!box) continue;
  154 |       expect(
  155 |         Math.max(box.height, box.width),
  156 |         `button ${index} is ${box.width}x${box.height}`,
  157 |       ).toBeGreaterThanOrEqual(40);
  158 |     }
  159 |   });
  160 | });
  161 | 
```