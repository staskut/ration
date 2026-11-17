/**
 * The week board.
 *
 * Changes save immediately — no explicit save button. A planner editing a week
 * makes dozens of small changes, and a save step turns every one into two
 * actions and an opportunity to lose work.
 */
import { useState } from "react";

import { ErrorState, Loading } from "../../components/Status";
import {
  useAddEntry,
  useModules,
  usePlan,
  useProfile,
  useRemoveEntry,
  useSetDayTemplate,
  useSetPortion,
} from "../../lib/queries";
import { useSession } from "../../lib/session";
import { usePlanSocket } from "../../lib/usePlanSocket";
import { ValidationPanel } from "./ValidationPanel";

const SLOTS = ["breakfast", "lunch", "snack", "dinner", "treat"] as const;
const TEMPLATES = ["normal", "long_shift", "training", "duty_24h"] as const;

export function PlanBuilder({ planId }: { planId: string }) {
  const { t } = useSession();
  const { data: plan, isLoading, isError, refetch } = usePlan(planId);
  const { data: profile } = useProfile(plan?.profile_id);
  const { data: modules } = useModules();
  const addEntry = useAddEntry(planId);
  const removeEntry = useRemoveEntry(planId);
  const setTemplate = useSetDayTemplate(planId);
  const setPortion = useSetPortion(planId);
  const [adding, setAdding] = useState<{ day: number; slot: string } | null>(null);
  const [highlighted, setHighlighted] = useState<number | null>(null);

  usePlanSocket(planId);

  if (isLoading) return <Loading t={t} />;
  if (isError || !plan) return <ErrorState t={t} onRetry={() => void refetch()} />;

  const failure =
    addEntry.error ?? removeEntry.error ?? setTemplate.error ?? setPortion.error;

  // A plan is always seven days (PRD 6). The reference week fills six of them
  // on purpose, so the seventh is not a gap to hide — but shown as "0 kcal
  // against a target of 1,700" it reads as a day that failed rather than a
  // day nobody has written yet.
  const planned = plan.days.filter((day) => day.entries.length > 0).length;

  return (
    <main className="mx-auto max-w-6xl px-4 pb-16">
      <div className="py-4">
        <h1 className="text-xl font-semibold">{plan.name}</h1>
        <p className="text-sm text-slate-500">
          {t.t("plan.days_planned", { planned, total: plan.days.length })}
        </p>
      </div>

      {failure && (
        <p role="alert" className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-900">
          {failure.message}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-3">
          {plan.days.map((day) => (
            <section
              key={day.day_index}
              id={`day-${day.day_index}`}
              className={[
                "rounded-2xl border p-3 transition",
                highlighted === day.day_index
                  ? "border-slate-900 ring-2 ring-slate-900/10"
                  : "border-slate-200",
              ].join(" ")}
            >
              <header className="flex items-baseline justify-between gap-2">
                <div>
                  <h2 className="font-medium">
                    Day {day.day_index + 1} · {day.date}
                  </h2>
                  {day.entries.length === 0 ? (
                    <p className="text-sm text-slate-400">{t.t("plan.day_unplanned")}</p>
                  ) : (
                  <p className="text-sm text-slate-500">
                    {t.kcal(day.kcal)} kcal
                    {profile && (
                      // Totals mean nothing without the target beside them.
                      <span className="text-slate-400">
                        {" "}
                        / {t.kcal(profile.daily_kcal_target)} ±{" "}
                        {t.kcal(profile.daily_kcal_tolerance)}
                      </span>
                    )}{" "}
                    · {t.grams(day.protein_g)} g protein
                    {profile && (
                      <span className="text-slate-400">
                        {" "}
                        / min {t.grams(profile.daily_protein_min)}
                      </span>
                    )}
                  </p>
                  )}
                </div>
                <select
                  value={day.day_template}
                  onChange={(event) =>
                    setTemplate.mutate({
                      dayIndex: day.day_index,
                      template: event.target.value,
                    })
                  }
                  className="min-h-(--spacing-tap) rounded-lg border border-slate-300 px-2 text-sm"
                  aria-label={`Day template ${day.day_index + 1}`}
                >
                  {TEMPLATES.map((template) => (
                    <option key={template} value={template}>
                      {t.template(template)}
                    </option>
                  ))}
                </select>
              </header>

              <div className="mt-2 grid gap-2 sm:grid-cols-5">
                {SLOTS.map((slot) => {
                  const entries = day.entries.filter((entry) => entry.slot === slot);
                  const totals = day.slot_totals?.find((item) => item.slot === slot);
                  return (
                    <div key={slot} className="rounded-xl bg-slate-50 p-2">
                      <p className="flex justify-between text-xs text-slate-500">
                        <span>{t.slot(slot)}</span>
                        {totals && <span>{t.kcal(totals.kcal)}</span>}
                      </p>

                      {entries.map((entry) => (
                        <div
                          key={entry.id}
                          className="mt-1 rounded-lg bg-white px-2 py-1 text-sm"
                        >
                          <span className="block truncate">{entry.module_name}</span>
                          <span className="text-xs text-slate-400">
                            {entry.role === "side" ? "side" : "main"}
                          </span>
                          <label className="mt-1 flex items-center gap-1 text-xs text-slate-500">
                            <span className="sr-only">
                              Portion factor for {entry.module_name}
                            </span>
                            <input
                              type="range"
                              min={0.5}
                              max={1.5}
                              step={0.1}
                              defaultValue={Number(entry.portion_factor)}
                              onChange={(event) =>
                                setPortion.mutate({
                                  entryId: entry.id,
                                  portionFactor: event.target.value,
                                })
                              }
                              className="w-full"
                              aria-label={`Portion factor for ${entry.module_name}`}
                            />
                            <span className="tabular-nums">
                              ×{t.factor(entry.portion_factor)}
                            </span>
                          </label>
                          <button
                            type="button"
                            onClick={() => removeEntry.mutate(entry.id)}
                            className="float-right text-slate-400 hover:text-rose-600"
                            aria-label={`Remove ${entry.module_name}`}
                          >
                            ×
                          </button>
                        </div>
                      ))}

                      {adding?.day === day.day_index && adding.slot === slot ? (
                        <select
                          autoFocus
                          defaultValue=""
                          onChange={(event) => {
                            if (event.target.value) {
                              addEntry.mutate({
                                dayIndex: day.day_index,
                                slot,
                                moduleId: event.target.value,
                              });
                            }
                            setAdding(null);
                          }}
                          onBlur={() => setAdding(null)}
                          className="mt-1 w-full rounded-lg border border-slate-300 text-sm"
                        >
                          <option value="">—</option>
                          {modules
                            ?.filter((module) => module.slot === slot)
                            .filter(
                              (module) =>
                                // A slot takes one main. Offering a second and
                                // then refusing it with a 409 is a worse
                                // experience than not offering it.
                                module.role !== "main" ||
                                !entries.some((existing) => existing.role === "main"),
                            )
                            .map((module) => (
                              <option key={module.id} value={module.id}>
                                {module.name}
                              </option>
                            ))}
                        </select>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setAdding({ day: day.day_index, slot })}
                          className="mt-1 w-full rounded-lg border border-dashed border-slate-300 py-1 text-xs text-slate-400"
                        >
                          +
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>

        <div>
          <ValidationPanel
            planId={planId}
            onSelect={(dayIndex) => {
              if (dayIndex === null) return;
              setHighlighted(dayIndex);
              document
                .getElementById(`day-${dayIndex}`)
                ?.scrollIntoView({ behavior: "smooth", block: "center" });
            }}
          />
          <p className="mt-3 text-xs text-slate-400">
            The portion factor scales quantities linearly — salt and oil do
            not scale that way.
          </p>
        </div>
      </div>
    </main>
  );
}
