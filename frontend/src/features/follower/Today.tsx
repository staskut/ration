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
import { usePlans, useToday } from "../../lib/queries";
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

/** The active plan's week, for a day that falls outside it. */
function planWeek(plans: { start_date: string; status: string }[] | undefined) {
  const plan = plans?.find((p) => p.status === "active") ?? plans?.[0];
  if (!plan) return null;
  return { first: plan.start_date, last: shiftDate(plan.start_date, 6) };
}

export function Today() {
  const { t } = useSession();
  const [date, setDate] = useState(todayIso);
  const { data, isLoading, isError, error, refetch } = useToday(date);
  // Only consulted when the day falls outside the plan, which is why it is
  // not gated: the query is cached and the follower's nav already holds it.
  const { data: plans } = usePlans();

  usePlanSocket(data?.plan_id);

  // The day navigation renders whatever the query did, and that is the whole
  // point of it. It used to live inside the success branch, so a date outside
  // the plan's week — which is every date once the week has passed — produced
  // an error screen with no way off it. The follower's own screen became a
  // dead end on the day the plan ran out, and the public demo sat like that
  // for a month before anything noticed (#75).
  const header = (
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
            {date}
            {data && ` · ${t.template(data.day_template)}`}
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
      {data && (
        <p className="mt-2 text-center text-sm text-slate-600">
          {t.t("today.day_total", {
            kcal: t.kcal(data.kcal),
            protein: t.grams(data.protein_g),
          })}
        </p>
      )}
    </header>
  );

  if (isLoading && !data) {
    return (
      <main className="mx-auto max-w-xl px-4 pb-16">
        {header}
        <Loading t={t} />
      </main>
    );
  }

  if (isError || !data) {
    // A 404 is not a failure: it is a date with no plan behind it, which is
    // the ordinary state of every day outside the current week. Saying
    // "something went wrong" there sends the follower looking for a fault
    // that is not there.
    const outsidePlan = error?.status === 404;
    const week = planWeek(plans);
    return (
      <main className="mx-auto max-w-xl px-4 pb-16">
        {header}
        {outsidePlan ? (
          <div className="px-4 py-8 text-center">
            <p className="text-slate-400">{t.t("today.outside_plan")}</p>
            {/* The plan's own dates, and one tap to reach them. Saying only
                "this day is outside the plan" leaves the follower guessing
                which direction to walk and how far — which, for a plan a
                fortnight behind, is fourteen blind taps. */}
            {week && (
              <>
                <p className="mt-2 text-sm text-slate-500">
                  {t.t("today.plan_week")}: {week.first} – {week.last}
                </p>
                <button
                  type="button"
                  onClick={() => setDate(week.first)}
                  className="mt-4 min-h-(--spacing-tap) rounded-lg bg-slate-900 px-4 text-white"
                >
                  {t.t("today.go_to_plan")}
                </button>
              </>
            )}
          </div>
        ) : (
          <ErrorState t={t} onRetry={() => void refetch()} />
        )}
      </main>
    );
  }

  const planned = data.slots.some((slot) => slot.entries.length > 0);

  return (
    <main className="mx-auto max-w-xl px-4 pb-16">
      {header}

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
                <span>{t.t("today.slot_kcal", { kcal: t.kcal(slot.kcal) })}</span>
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
                        {t.t("today.entry_line", {
                          grams: t.grams(entry.portion_grams),
                          kcal: t.kcal(entry.kcal),
                          protein: t.grams(entry.protein_g),
                        })}
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
