# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: wsprobe.spec.ts >> instrument
- Location: wsprobe.spec.ts:3:1

# Error details

```
Error: expect(received).toBe(expected) // Object.is equality

Expected: true
Received: false
```

# Page snapshot

```yaml
- generic [ref=f1e2]:
  - main [ref=f1e3]:
    - generic [ref=f1e4]:
      - generic [ref=f1e5]:
        - button "Вчера" [ref=f1e6]: ‹
        - generic [ref=f1e7]:
          - heading "Сегодня" [level=1] [ref=f1e8]
          - paragraph [ref=f1e9]: 2026-10-18 · Обычный день
        - button "Завтра" [active] [ref=f1e10]: ›
      - paragraph [ref=f1e11]: "Итого за день: 0 ккал · 0 г"
    - paragraph [ref=f1e12]: На этот день ничего не запланировано
  - navigation [ref=f1e13]:
    - button "Сегодня" [ref=f1e14]
    - button "Список покупок" [ref=f1e15]
```

# Test source

```ts
  1  | import { expect, test } from "./fixtures";
  2  | 
  3  | test("instrument", async ({ planner, follower }) => {
  4  |   const log: string[] = [];
  5  |   follower.on("websocket", (ws) => {
  6  |     log.push(`WS OPEN ${Date.now() % 100000}`);
  7  |     ws.on("framereceived", (f) => log.push(`FRAME ${Date.now() % 100000} ${String(f.payload).slice(0, 90)}`));
  8  |     ws.on("close", () => log.push(`WS CLOSE ${Date.now() % 100000}`));
  9  |   });
  10 |   follower.on("requestfinished", (r) => {
  11 |     if (r.url().includes("/api/today")) log.push(`GET today ${Date.now() % 100000} ${r.url().split("?")[1] ?? ""}`);
  12 |   });
  13 | 
  14 |   await follower.goto("/");
  15 |   const empty = follower.getByText("На этот день ничего не запланировано");
  16 |   for (let i = 0; i < 7; i += 1) {
  17 |     if (await empty.waitFor({ state: "visible", timeout: 3000 }).then(() => true).catch(() => false)) break;
  18 |     const tm = follower.getByLabel("Завтра");
  19 |     if (!(await tm.isVisible().catch(() => false))) break;
  20 |     await tm.click();
  21 |   }
  22 |   log.push(`--- on empty day ${Date.now() % 100000} ---`);
  23 | 
  24 |   await planner.locator("nav").getByRole("button", { name: "План" }).click();
  25 |   const lastDay = planner.locator("#day-6");
  26 |   await lastDay.scrollIntoViewIfNeeded();
  27 |   await lastDay.getByRole("button", { name: "+" }).nth(3).click();
  28 |   const picker = lastDay.locator("select").nth(1);
  29 |   await expect(picker).toBeVisible();
  30 |   await picker.selectOption({ index: 1 });
  31 |   log.push(`--- planner selected ${Date.now() % 100000} ---`);
  32 | 
  33 |   const hidden = await empty.waitFor({ state: "hidden", timeout: 15000 }).then(() => true).catch(() => false);
  34 |   log.push(`--- hidden=${hidden} ${Date.now() % 100000} ---`);
  35 |   console.log("\n" + log.join("\n"));
> 36 |   expect(hidden).toBe(true);
     |                  ^ Error: expect(received).toBe(expected) // Object.is equality
  37 | });
  38 | 
```