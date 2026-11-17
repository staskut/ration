import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  CATALOGS,
  createTranslator,
  formatQuantity,
  renderFinding,
  roundDecimal,
  type Locale,
} from "../src/lib/i18n";

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

/**
 * Every component, so the sweep cannot miss one by being written after it.
 */
function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

describe("no component spells a string itself", () => {
  // The last translation pass moved every screen to English and still left
  // "г", "ккал" and "шт" sitting in Today and the shopping list as literals.
  // They rendered Russian under every locale, because no locale setting can
  // reach a string that was never a key. Catalog completeness does not catch
  // that — the key existed and was simply not used — so this reads the source.
  const root = resolve(import.meta.dirname, "../src");
  const catalog = resolve(root, "lib/i18n/messages.ts");

  it("leaves Cyrillic to the catalog", () => {
    const offenders = sourceFiles(root)
      .filter((path) => path !== catalog)
      .filter((path) => /[\u0400-\u04FF]/.test(readFileSync(path, "utf8")))
      .map((path) => relative(root, path));

    expect(offenders).toEqual([]);
  });

  // `ingredient.names.ru` is ASCII, so the sweep above cannot see it. It is
  // the same defect in a different disguise: a component deciding the
  // reader's language for itself. It rendered a Russian catalog under an
  // English UI, and the edit form wrote the name straight back to `ru`.
  it("leaves the choice of name to the translator", () => {
    const offenders = sourceFiles(root)
      .filter((path) => path !== catalog)
      .filter((path) => /\bnames\.(ru|en)\b/.test(readFileSync(path, "utf8")))
      .map((path) => relative(root, path));

    expect(offenders).toEqual([]);
  });
});

describe("naming a thing the catalog does not own", () => {
  it("prefers the reader's locale", () => {
    const t = createTranslator("en");
    expect(t.name({ ru: "Бананы", en: "Bananas" }, "banana")).toBe("Bananas");
  });

  it("falls back to any name before the identifier", () => {
    // Half the catalog could be named in one language only. A slug is a
    // worse answer than the name somebody actually wrote.
    const t = createTranslator("en");
    expect(t.name({ ru: "Бананы" }, "banana")).toBe("Бананы");
  });

  it("falls back to the identifier when there is no name at all", () => {
    const t = createTranslator("en");
    expect(t.name({}, "banana")).toBe("banana");
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
    expect(text).toContain("1,578");
    expect(text).toContain("1,650");
  });

  it("shows a one-based day, because day 0 means nothing to a reader", () => {
    expect(renderFinding(finding, "en")).toContain("Day 1");
    expect(renderFinding(finding, "ru")).toContain("День 1");
  });

  it("uses the locale's separators", () => {
    // Russian groups thousands with a space, because a comma there is its
    // decimal point. A protein finding keeps the tenth a kcal one drops.
    expect(renderFinding(finding, "ru")).toContain("1\u00a0578");
    expect(renderFinding(finding, "en")).toContain("1,578");
    const protein = {
      ...finding,
      message_key: "validation.day_protein_below_min",
      params: { actual: "98.44", min: "105" },
    };
    expect(renderFinding(protein, "ru")).toContain("98,4");
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

  it("formats numbers for the locale, at the precision each quantity earns", () => {
    expect(createTranslator("ru").grams("553.8")).toBe("553,8");
    expect(createTranslator("en").grams("553.8")).toBe("553.8");
    expect(createTranslator("en").kcal("553.8")).toBe("554");
    expect(createTranslator("en").factor("0.65")).toBe("0.65");
    // `exact` is for a value on its way into an input, where rounding would
    // silently rewrite what the planner stored.
    expect(createTranslator("en").exact("0.6500")).toBe("0.6500");
  });
});

describe("numbers for a reader", () => {
  it("rounds half-up without going through a float", () => {
    // 1577.59 is not representable in binary; the point of rounding the
    // string is that this answer never depends on that.
    expect(roundDecimal("1577.59", 0)).toBe("1578");
    expect(roundDecimal("1577.59", 1)).toBe("1577.6");
    expect(roundDecimal("128.404", 1)).toBe("128.4");
    expect(roundDecimal("31.764", 1)).toBe("31.8");
    expect(roundDecimal("0.5", 0)).toBe("1");
    expect(roundDecimal("0.45", 1)).toBe("0.5");
  });

  it("carries across nines", () => {
    expect(roundDecimal("9.99", 1)).toBe("10.0");
    expect(roundDecimal("99.95", 1)).toBe("100.0");
    expect(roundDecimal("999.5", 0)).toBe("1000");
  });

  it("never reports minus zero", () => {
    expect(roundDecimal("-0.04", 1)).toBe("0.0");
    expect(formatQuantity("-0.04", "en", 1)).toBe("0");
    expect(roundDecimal("-1.26", 1)).toBe("-1.3");
  });

  it("leaves a value it does not recognise alone", () => {
    // Better to show the raw string than to invent a number for it.
    expect(roundDecimal("", 1)).toBe("");
    expect(roundDecimal("1e3", 1)).toBe("1e3");
  });

  it("drops a trailing zero rather than claiming precision", () => {
    expect(formatQuantity("2000", "en", 1)).toBe("2,000");
    expect(formatQuantity("2000.04", "en", 1)).toBe("2,000");
  });

  it("groups thousands the way each locale reads them", () => {
    expect(formatQuantity("1577.59", "en", 0)).toBe("1,578");
    // A comma between thousands would read as a decimal point in Russian.
    expect(formatQuantity("1577.59", "ru", 0)).toBe("1 578");
    expect(formatQuantity("128.404", "ru", 1)).toBe("128,4");
    expect(formatQuantity("-1577.5", "en", 0)).toBe("-1,578");
  });

  it("keeps the second decimal of a factor, which changes the meal", () => {
    expect(formatQuantity("0.65", "en", 2)).toBe("0.65");
    expect(formatQuantity("1.2", "en", 2)).toBe("1.2");
  });

  it("rounds a finding to match the screen beside it", () => {
    const finding = {
      level: "error" as const,
      code: "day_kcal_out_of_range",
      message_key: "validation.day_kcal_out_of_range",
      params: { actual: "1577.59", min: "1650", max: "1750" },
      day_index: 2,
    };
    // The day header for the same day reads "1,578 kcal". One number, shown
    // twice, must not look like two.
    expect(renderFinding(finding, "en")).toBe("Day 3: 1,578 kcal, target 1,650–1,750");
  });

  it("keeps a tenth of a gram in a protein finding", () => {
    const finding = {
      level: "error" as const,
      code: "day_protein_below_min",
      message_key: "validation.day_protein_below_min",
      params: { actual: "98.44", min: "105" },
      day_index: 0,
    };
    expect(renderFinding(finding, "en")).toBe("Day 1: 98.4 g protein, minimum 105");
  });
});
