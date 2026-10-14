/**
 * What to eat and what to pack, in one screen.
 *
 * The whole interaction has to fit in about thirty seconds (PRD §2.1): no
 * scrolling to find today, no menu, no second screen. Everything below is
 * shaped by that — one request, slot times from the day's template, and
 * yesterday and tomorrow one tap away.
 */
import { useState } from "react";

import { Empty, ErrorState, Loading } from "../../components/Status";
import { useToday } from "../../lib/queries";
import { useSession } from "../../lib/session";
import { usePlanSocket } from "../../lib/usePlanSocket";
import { Rating } from "./Rating";

function shiftDate(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function Today() {
  const { t } = useSession();
  const [date, setDate] = useState(todayIso);
  const { data, isLoading, isError, refetch } = useToday(date);

  usePlanSocket(data?.plan_id);

  if (isLoading) return <Loading t={t} />;
  if (isError || !data) return <ErrorState t={t} onRetry={() => void refetch()} />;

  const planned = data.slots.some((slot) => slot.entries.length > 0);

  return (
    <main className="mx-auto max-w-xl px-4 pb-16">
      <header className="sticky top-0 bg-white/95 py-3 backdrop-blur">
        <div className="flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => setDate(shiftDate(date, -1))}
            className="min-h-(--spacing-tap) min-w-(--spacing-tap) rounded-lg border border-slate-200"
            aria-label={t.t("today.yesterday")}
          >
            ‹
          </button>
          <div className="text-center">
            <h1 className="text-lg font-semibold">{t.t("today.title")}</h1>
            <p className="text-sm text-slate-500">
              {date} · {t.template(data.day_template)}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setDate(shiftDate(date, 1))}
            className="min-h-(--spacing-tap) min-w-(--spacing-tap) rounded-lg border border-slate-200"
            aria-label={t.t("today.tomorrow")}
          >
            ›
          </button>
        </div>
        {/* Day totals sit in the header so they need no scrolling. */}
        <p className="mt-2 text-center text-sm text-slate-600">
          {t.t("today.total")}: {t.number(data.kcal)} ккал · {t.number(data.protein_g)} г
        </p>
      </header>

      {!planned && <Empty>{t.t("today.nothing_planned")}</Empty>}

      {planned &&
        data.slots
          .filter((slot) => slot.entries.length > 0)
          .map((slot) => (
            <section key={slot.slot} className="mt-5">
              <h2 className="flex items-baseline justify-between text-sm font-medium text-slate-500">
                <span>
                  {slot.time} · {t.slot(slot.slot)}
                </span>
                <span>{t.number(slot.kcal)} ккал</span>
              </h2>

              {slot.entries.map((entry) => (
                <article
                  key={entry.entry_id}
                  className="mt-2 rounded-2xl border border-slate-200 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="font-medium">{entry.module_name}</h3>
                      <p className="text-sm text-slate-500">
                        {t.number(entry.portion_grams)} г · {t.number(entry.kcal)} ккал ·{" "}
                        {t.number(entry.protein_g)} г белка
                      </p>
                      {entry.home_only && (
                        <span className="mt-1 inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-900">
                          {t.t("today.home_only")}
                        </span>
                      )}
                      {(entry.critical_notes ?? []).map((note) => (
                        <p key={note} className="mt-1 text-xs font-medium text-rose-700">
                          {note}
                        </p>
                      ))}
                    </div>
                  </div>

                  <div className="mt-3">
                    <Rating
                      planId={data.plan_id}
                      entryId={entry.entry_id}
                      current={(entry.feedback?.rating as never) ?? null}
                      t={t}
                    />
                  </div>
                </article>
              ))}
            </section>
          ))}
    </main>
  );
}
