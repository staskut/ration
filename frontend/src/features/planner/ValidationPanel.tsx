/**
 * Every rule violation in one place.
 *
 * Findings are phrased as violations of the planner's own configured rules,
 * never as health judgements (PRD §7). The engine emits a key and parameters;
 * the sentence is built here, which is what keeps the follower's Russian
 * screens possible.
 */
import type { Finding } from "../../lib/i18n";
import { useValidation } from "../../lib/queries";
import { useSession } from "../../lib/session";

const TONE: Record<string, string> = {
  error: "border-rose-300 bg-rose-50 text-rose-900",
  warning: "border-amber-300 bg-amber-50 text-amber-900",
  info: "border-slate-200 bg-slate-50 text-slate-500",
};

export function ValidationPanel({
  planId,
  onSelect,
}: {
  planId: string;
  onSelect?: (dayIndex: number | null) => void;
}) {
  const { t } = useSession();
  const { data, isLoading } = useValidation(planId);

  if (isLoading || !data) return null;

  if (data.findings.length === 0) {
    // An explicit state, never a blank panel: nothing to show and failed to
    // load look identical otherwise.
    return (
      <aside className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-900">
        {t.t("validation.clean")}
      </aside>
    );
  }

  const byDay = new Map<number, Finding[]>();
  for (const finding of data.findings as Finding[]) {
    const day = finding.day_index ?? -1;
    byDay.set(day, [...(byDay.get(day) ?? []), finding]);
  }

  return (
    <aside className="space-y-3">
      <p className="text-sm text-slate-600">
        {t.t("validation.errors", { count: data.error_count })} ·{" "}
        {t.t("validation.warnings", { count: data.warning_count })}
      </p>

      {[...byDay.entries()]
        .sort(([a], [b]) => a - b)
        .map(([day, findings]) => (
          <section key={day}>
            {day >= 0 && (
              <h3 className="text-xs font-medium uppercase tracking-wide text-slate-400">
                День {day + 1}
              </h3>
            )}
            <ul className="mt-1 space-y-1">
              {findings.map((finding, index) => (
                <li key={`${finding.code}-${finding.slot ?? ""}-${index}`}>
                  <button
                    type="button"
                    onClick={() => onSelect?.(finding.day_index ?? null)}
                    className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${TONE[finding.level]}`}
                  >
                    {t.finding(finding)}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
    </aside>
  );
}
