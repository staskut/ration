import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { CATALOGS, createTranslator, renderFinding, type Locale } from "../src/lib/i18n";

const LOCALES: Locale[] = ["ru", "en"];

/**
 * The message keys the backend can actually emit, read from its source rather
 * than copied here. A hand-maintained list would pass forever after someone
 * added a twelfth finding, which is exactly the failure this guards.
 */
function backendMessageKeys(): string[] {
  const source = readFileSync(
    resolve(import.meta.dirname, "../../backend/src/ration/domain/validation.py"),
    "utf8",
  );
  const keys = [...source.matchAll(/message_key="([^"]+)"/g)].map((m) => m[1]!);
  return [...new Set(keys)].sort();
}

describe("validation message completeness", () => {
  it("reads a plausible number of keys from the backend", () => {
    // Guards the extraction itself: a changed quoting style would silently
    // yield zero keys and make every test below pass over an empty list.
    expect(backendMessageKeys().length).toBeGreaterThanOrEqual(10);
  });

  it.each(LOCALES)("%s translates every code the backend can emit", (locale) => {
    const missing = backendMessageKeys().filter(
      (key) => !(key in CATALOGS[locale].validation),
    );
    expect(missing).toEqual([]);
  });

  it.each(LOCALES)("%s has no translation for a code that no longer exists", (locale) => {
    const known = new Set(backendMessageKeys());
    const orphaned = Object.keys(CATALOGS[locale].validation).filter(
      (key) => !known.has(key),
    );
    expect(orphaned).toEqual([]);
  });

  it("both locales cover the same keys", () => {
    expect(Object.keys(CATALOGS.ru.validation).sort()).toEqual(
      Object.keys(CATALOGS.en.validation).sort(),
    );
  });

  it.each(LOCALES)("%s covers every slot, template and shop section", (locale) => {
    const catalog = CATALOGS[locale];
    expect(Object.keys(catalog.slot).sort()).toEqual(
      ["breakfast", "dinner", "lunch", "snack", "treat"],
    );
    expect(Object.keys(catalog.template).sort()).toEqual(
      ["duty_24h", "long_shift", "normal", "training"],
    );
    expect(Object.keys(catalog.section)).toHaveLength(10);
  });

  it.each(LOCALES)("%s and the other locale share every UI key", (locale) => {
    const other = locale === "ru" ? "en" : "ru";
    expect(Object.keys(CATALOGS[locale].ui).sort()).toEqual(
      Object.keys(CATALOGS[other].ui).sort(),
    );
  });
});

describe("rendering a finding", () => {
  const finding = {
    level: "error" as const,
    code: "DAY_KCAL_OUT_OF_RANGE",
    message_key: "validation.day_kcal_out_of_range",
    params: { actual: "1577.6", min: "1650.0", max: "1750.0" },
    day_index: 0,
  };

  it("interpolates the numbers into a sentence", () => {
    const text = renderFinding(finding, "en");
    expect(text).toContain("1577.6");
    expect(text).toContain("1650.0");
  });

  it("shows a one-based day, because day 0 means nothing to a reader", () => {
    expect(renderFinding(finding, "en")).toContain("Day 1");
    expect(renderFinding(finding, "ru")).toContain("День 1");
  });

  it("uses the locale's decimal separator", () => {
    expect(renderFinding(finding, "ru")).toContain("1577,6");
    expect(renderFinding(finding, "en")).toContain("1577.6");
  });

  it("translates the slot name rather than printing the enum", () => {
    const slotFinding = {
      ...finding,
      message_key: "validation.slot_kcal_out_of_budget",
      slot: "dinner",
    };
    expect(renderFinding(slotFinding, "ru")).toContain("Ужин");
    expect(renderFinding(slotFinding, "en")).toContain("Dinner");
  });

  it("translates a day template inside the parameters", () => {
    const gate = {
      ...finding,
      message_key: "validation.template_gate_violated",
      params: { tag: "alcohol", template: "training" },
    };
    expect(renderFinding(gate, "ru")).toContain("Тренировка");
  });

  it("leaves non-numeric parameters alone", () => {
    const excluded = {
      ...finding,
      message_key: "validation.excluded_ingredient",
      slot: "lunch",
      params: { ingredient: "Куриная грудка", module: "x" },
    };
    expect(renderFinding(excluded, "ru")).toContain("Куриная грудка");
  });

  it("falls back to the code if a key is somehow missing", () => {
    const unknown = { ...finding, message_key: "validation.does_not_exist" };
    expect(renderFinding(unknown, "ru")).toBe("DAY_KCAL_OUT_OF_RANGE");
  });

  it.each(LOCALES)("%s renders every key without leaving a placeholder", (locale) => {
    // A sentence still containing {something} means a parameter was never
    // supplied — visible nonsense on screen, so it fails here instead.
    for (const key of Object.keys(CATALOGS[locale].validation)) {
      const text = renderFinding(
        {
          ...finding,
          message_key: key,
          slot: "dinner",
          params: {
            actual: "1", min: "2", max: "3", threshold: "4", tag: "t",
            template: "normal", ingredient: "i", module: "m", days: "0,1",
          },
        },
        locale,
      );
      expect(text, `${locale}: ${key}`).not.toMatch(/\{[a-z_]+\}/);
    }
  });
});

describe("the translator", () => {
  it("interpolates UI parameters", () => {
    const t = createTranslator("ru");
    expect(t.t("shopping.progress", { done: 3, total: 12 })).toBe("3 из 12");
  });

  it("returns the key when one is missing rather than throwing", () => {
    expect(createTranslator("ru").t("nothing.here")).toBe("nothing.here");
  });

  it("formats numbers for the locale", () => {
    expect(createTranslator("ru").number("553.8")).toBe("553,8");
    expect(createTranslator("en").number("553.8")).toBe("553.8");
  });
});
