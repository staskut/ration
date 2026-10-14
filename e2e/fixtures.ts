import { test as base, type Page } from "@playwright/test";

/**
 * Two browser contexts, one per role.
 *
 * Separate contexts rather than separate tests: the point is that a change by
 * one person reaches the other *while they are looking at it*, which cannot be
 * observed by signing in and out of a single session.
 */
export const PLANNER = "planner@ration.example";
export const FOLLOWER = "follower@ration.example";
export const PASSWORD = process.env.RATION_E2E_PASSWORD ?? "correct-horse-battery";

export async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/");
  await page.getByPlaceholder("Почта").fill(email);
  await page.getByPlaceholder("Пароль").fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  // Wait on the signed-in UI rather than on a timeout.
  await page.waitForSelector("nav", { state: "visible" });
}

export const test = base.extend<{ planner: Page; follower: Page }>({
  planner: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await signIn(page, PLANNER);
    await use(page);
    await context.close();
  },
  follower: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await signIn(page, FOLLOWER);
    await use(page);
    await context.close();
  },
});

export { expect } from "@playwright/test";
