/**
 * Regenerate the README's screenshots.
 *
 * A committed PNG goes stale silently — it keeps showing a screen that no
 * longer exists, and nothing fails. This script is here so the images are
 * reproducible rather than archaeological: point it at a running stack and
 * it overwrites them.
 *
 *   make screenshots
 *
 * Deliberately not a test. It asserts nothing, and a failure to render a
 * pretty picture should not turn the suite red.
 */
import { mkdir } from "node:fs/promises";
import { chromium, devices } from "@playwright/test";

const BASE = process.env.RATION_BASE_URL ?? "http://localhost:8000";
const PASSWORD = process.env.RATION_E2E_PASSWORD ?? "correct-horse-battery";
const OUT = new URL("../docs/images/", import.meta.url).pathname;

async function signIn(page, email) {
  await page.goto(BASE);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForSelector("nav", { state: "visible" });
}

const shots = [
  {
    file: "planner-week.png",
    viewport: { width: 1280, height: 900 },
    email: "planner@ration.example",
    async act(page) {
      await page.getByText(/of 7 days planned/).waitFor();
    },
  },
  {
    file: "planner-catalog.png",
    viewport: { width: 1280, height: 900 },
    email: "planner@ration.example",
    async act(page) {
      await page.getByRole("button", { name: "Ingredients" }).click();
      await page.getByRole("heading", { name: "Ingredients" }).waitFor();
    },
  },
  {
    file: "follower-today.png",
    viewport: { width: 375, height: 812 },
    email: "follower@ration.example",
    // Viewport, not full page: the tab bar is `position: fixed`, and a
    // full-page capture paints it across the middle of the image rather than
    // at the bottom of the screen where a reader actually sees it.
    fullPage: false,
    async act(page) {
      await page.getByRole("heading", { name: "Today" }).waitFor();
    },
  },
];

const browser = await chromium.launch();
await mkdir(OUT, { recursive: true });

for (const shot of shots) {
  const context = await browser.newContext({
    ...devices["Desktop Chrome"],
    viewport: shot.viewport,
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  await signIn(page, shot.email);
  await shot.act(page);
  // The planner's boards are taller than any viewport worth screenshotting,
  // so a full-page capture is the honest one for those.
  await page.screenshot({ path: OUT + shot.file, fullPage: shot.fullPage !== false });
  console.log("wrote", shot.file);
  await context.close();
}

await browser.close();
