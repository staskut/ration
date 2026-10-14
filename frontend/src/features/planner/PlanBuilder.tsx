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
  useRemoveEntry,
  useSetDayTemplate,
} from "../../lib/queries";
import { useSession } from "../../lib/session";
import { usePlanSocket } from "../../lib/usePlanSocket";
import { ValidationPanel } from "./ValidationPanel";

const SLOTS = ["breakfast", "lunch", "snack", "dinner", "treat"] as const;
const TEMPLATES = ["normal", "long_shift", "training", "duty_24h"] as const;

export function PlanBuilder({ planId }: { planId: string }) {
  const { t } = useSession();
  const { data: plan, isLoading, isError, refetch } = usePlan(planId);
  const { data: modules } = useModules();
  const addEntry = useAddEntry(planId);
  const removeEntry = useRemoveEntry(planId);
  const setTemplate = useSetDayTemplate(planId);
  const [adding, setAdding] = useState<{ day: number; slot: string } | null>(null);

  usePlanSocket(planId);

  if (isLoading) return <Loading t={t} />;
  if (isError || !plan) return <ErrorState t={t} onRetry={() => void refetch()} />;

  const failure = addEntry.error ?? removeEntry.error ?? setTemplate.error;

  return (
    <main className="mx-auto max-w-6xl px-4 pb-16">
      <h1 className="py-4 text-xl font-semibold">{plan.name}</h1>

      {failure && (
        <p role="alert" className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-900">
          {failure.message}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-3">
          {plan.days.map((day) => (
            <section key={day.day_index} className="rounded-2xl border border-slate-200 p-3">
              <header className="flex items-baseline justify-between gap-2">
                <div>
                  <h2 className="font-medium">
                    День {day.day_index + 1} · {day.date}
                  </h2>
                  <p className="text-sm text-slate-500">
                    {t.number(day.kcal)} ккал · {t.number(day.protein_g)} г белка
                  </p>
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
                  aria-label={`Режим дня ${day.day_index + 1}`}
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
                        {totals && <span>{t.number(totals.kcal)}</span>}
                      </p>

                      {entries.map((entry) => (
                        <div
                          key={entry.id}
                          className="mt-1 rounded-lg bg-white px-2 py-1 text-sm"
                        >
                          <span className="block truncate">{entry.module_name}</span>
                          <span className="text-xs text-slate-400">
                            {entry.role === "side" ? "гарнир" : "основное"}
                          </span>
                          <button
                            type="button"
                            onClick={() => removeEntry.mutate(entry.id)}
                            className="float-right text-slate-400 hover:text-rose-600"
                            aria-label={`Убрать ${entry.module_name}`}
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

        <ValidationPanel planId={planId} />
      </div>
    </main>
  );
}
