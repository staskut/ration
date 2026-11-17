import { defineConfig, devices } from "@playwright/test";

/**
 * Against the compose stack, seeded with the reference plan.
 *
 * Chromium only. A browser matrix would triple the runtime to test a
 * two-person app that runs on two known devices, and the collaborative path
 * is the thing worth proving.
 */
export default defineConfig({
  testDir: ".",
  // No arbitrary sleeps anywhere: every wait is on a condition, which is what
  // keeps this out of the flaky-suite category teams learn to ignore.
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: process.env.RATION_BASE_URL ?? "http://localhost:8000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"] },
      // The phone-shaped assertions belong to the mobile project.
      grepInvert: /@mobile/,
    },
    {
      name: "mobile",
      // A phone-sized Chromium rather than devices["iPhone 13"], which is
      // WebKit and would contradict the Chromium-only decision above by
      // pulling in a second browser download.
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 375, height: 812 },
        isMobile: false,
        hasTouch: true,
      },
      // The follower's screens, and the planner's ingredient catalog. The
      // planner's week *board* is desktop-only by design (PRD §2), so running
      // it at 375px would test a promise the product does not make — but the
      // catalog is data management, which happens on whatever is to hand.
      grep: /@mobile/,
    },
  ],
});
