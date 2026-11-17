/**
 * Rendering text, including validation findings.
 *
 * The domain layer never produces a sentence — findings carry a `message_key`
 * and parameters — so this is where they become readable. That split is what
 * lets a screen change language without translating strings that were built on
 * a server, which is why switching the product to English cost almost nothing.
 */
import { CATALOGS, type Catalog, type Locale } from "./messages";

export type { Locale };
export { CATALOGS };

export interface Finding {
  level: "error" | "warning" | "info";
  code: string;
  message_key: string;
  params: Record<string, string>;
  day_index?: number | null;
  slot?: string | null;
  entry_id?: string | null;
}

/**
 * How each locale writes a number. The thousands separator matters as much as
 * the decimal one: a comma between thousands reads as a decimal point to a
 * Russian reader, so `1,578` there would say "one and a half".
 */
const NUMBER_FORMATS: Record<Locale, { decimal: string; group: string }> = {
  ru: { decimal: ",", group: " " },
  en: { decimal: ".", group: "," },
};

/** Render a decimal string in the locale's convention, without rounding it. */
export function formatNumber(value: string, locale: Locale): string {
  return value.replace(".", NUMBER_FORMATS[locale].decimal);
}

const DECIMAL = /^(-?)(\d+)(?:\.(\d*))?$/;

/** Add one to a string of digits, carrying leftwards: "199" becomes "200". */
function carry(digits: string): string {
  const out = [...digits];
  for (let index = out.length - 1; index >= 0; index -= 1) {
    if (out[index] !== "9") {
      out[index] = String(Number(out[index]) + 1);
      return out.join("");
    }
    out[index] = "0";
  }
  return `1${out.join("")}`;
}

/**
 * Round a decimal string half-up to `places`, as string arithmetic.
 *
 * Decimals cross the API as strings precisely so that no binary float ever
 * touches them. Parsing one here to round it would put the drift back at the
 * last step before a reader — the one place nobody would catch it, because
 * the number still looks plausible. Returns the input unchanged if it is not
 * a plain decimal, so an unexpected shape degrades to showing the raw value.
 */
export function roundDecimal(value: string, places: number): string {
  const parts = DECIMAL.exec(value.trim());
  if (!parts) return value;
  const [, sign = "", whole = "0", fraction = ""] = parts;

  let digits = whole + fraction.slice(0, places).padEnd(places, "0");
  if ((fraction[places] ?? "0") >= "5") digits = carry(digits);

  const point = digits.length - places;
  const rounded =
    places === 0 ? digits : `${digits.slice(0, point)}.${digits.slice(point)}`;
  // A value that rounds to nothing is zero, not minus zero.
  return /^0(\.0*)?$/.test(rounded) ? rounded : sign + rounded;
}

/** Drop zeros that say nothing: "1578.0" is "1578", "31.80" is "31.8". */
function trimZeros(value: string): string {
  return value.includes(".") ? value.replace(/\.?0+$/, "") : value;
}

/**
 * A number as a reader wants it: rounded, with thousands grouped.
 *
 * `places` is a maximum, not a width. A plan whose day comes to exactly 2000
 * kcal should say "2,000", not "2,000.0" — the trailing zero reads as
 * precision that was never measured.
 */
export function formatQuantity(value: string, locale: Locale, places: number): string {
  const { decimal, group } = NUMBER_FORMATS[locale];
  const [whole = "", fraction] = trimZeros(roundDecimal(value, places)).split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, group);
  return fraction ? grouped + decimal + fraction : grouped;
}

function interpolate(template: string, params: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in params ? params[key]! : match,
  );
}

export function translate(
  catalog: Catalog,
  group: keyof Catalog,
  key: string,
): string | undefined {
  return catalog[group][key];
}

/**
 * Turn a finding into a sentence.
 *
 * Day indexes are zero-based internally and one-based for a reader: "day 0"
 * means nothing to someone looking at a week.
 *
 * Numbers are rounded to match the screen the finding is read beside. A panel
 * reporting "1,577.59 kcal" next to a day header reading "1,578 kcal" invites
 * the reader to wonder which of the two the engine actually used, and the
 * answer — both, it is one number shown twice — is not one they can reach
 * from the screen.
 */
export function renderFinding(finding: Finding, locale: Locale): string {
  const catalog = CATALOGS[locale];
  const template = catalog.validation[finding.message_key];
  if (!template) {
    // Should be unreachable: a completeness test fails the build when a code
    // has no translation. Showing the key beats showing nothing if it happens.
    return finding.code;
  }

  const places = finding.message_key.includes("kcal") ? 0 : 1;
  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(finding.params)) {
    params[key] = /^-?\d+(\.\d+)?$/.test(value)
      ? formatQuantity(value, locale, places)
      : value;
  }
  if (finding.day_index !== null && finding.day_index !== undefined) {
    params.day = String(finding.day_index + 1);
  }
  if (finding.slot) {
    params.slot = catalog.slot[finding.slot] ?? finding.slot;
  }
  if (params.template) {
    params.template = catalog.template[params.template] ?? params.template;
  }
  return interpolate(template, params);
}

export function createTranslator(locale: Locale) {
  const catalog = CATALOGS[locale];
  return {
    locale,
    t: (key: string, params: Record<string, string | number> = {}): string => {
      const template = catalog.ui[key];
      if (!template) return key;
      const stringified = Object.fromEntries(
        Object.entries(params).map(([k, v]) => [k, String(v)]),
      );
      return interpolate(template, stringified);
    },
    slot: (slot: string): string => catalog.slot[slot] ?? slot,
    template: (value: string): string => catalog.template[value] ?? value,
    section: (value: string): string => catalog.section[value] ?? value,
    /**
     * An entity's own name, which is data rather than a catalog key.
     * Falls back the way the server's `_display` does: the reader's
     * locale, then any name there is, then the identifier. A row named in
     * one language only still reads better in that language than as a slug.
     */
    name: (names: Record<string, string | undefined>, fallback: string): string =>
      names[locale] ?? Object.values(names).find(Boolean) ?? fallback,

    // Three precisions, because the quantities differ in what a reader can
    // act on. Nobody shops to a tenth of a calorie; a portion factor of 1.2
    // rounded to 1 would be a different meal.
    /** Energy, to the calorie: "1,578". */
    kcal: (value: string): string => formatQuantity(value, locale, 0),
    /** A weight, to a tenth of a gram: "128.4". */
    grams: (value: string): string => formatQuantity(value, locale, 1),
    /** A multiplier, where the second decimal is the point: "0.65". */
    factor: (value: string): string => formatQuantity(value, locale, 2),
    /** The stored value exactly as it is, for anything being edited. */
    exact: (value: string): string => formatNumber(value, locale),
    finding: (finding: Finding): string => renderFinding(finding, locale),
  };
}

export type Translator = ReturnType<typeof createTranslator>;
