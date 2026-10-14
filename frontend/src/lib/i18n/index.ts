/**
 * Rendering text, including validation findings.
 *
 * The domain layer never produces a sentence — findings carry a `message_key`
 * and parameters — so this is where they become readable. That split is what
 * makes the follower's Russian screens possible without translating strings
 * that were built on a server.
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

const DECIMAL_SEPARATOR: Record<Locale, string> = { ru: ",", en: "." };

/** Render a decimal string in the locale's convention, without rounding it. */
export function formatNumber(value: string, locale: Locale): string {
  return value.replace(".", DECIMAL_SEPARATOR[locale]);
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
 */
export function renderFinding(finding: Finding, locale: Locale): string {
  const catalog = CATALOGS[locale];
  const template = catalog.validation[finding.message_key];
  if (!template) {
    // Should be unreachable: a completeness test fails the build when a code
    // has no translation. Showing the key beats showing nothing if it happens.
    return finding.code;
  }

  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(finding.params)) {
    params[key] = /^-?\d+(\.\d+)?$/.test(value) ? formatNumber(value, locale) : value;
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
    number: (value: string): string => formatNumber(value, locale),
    finding: (finding: Finding): string => renderFinding(finding, locale),
  };
}

export type Translator = ReturnType<typeof createTranslator>;
