/**
 * The batch cook sessions, which until now were computed and unreachable.
 *
 * A session is derived, never stored: it is what the plan already implies,
 * read back. So there is nothing to edit here, and editing the plan changes
 * this screen rather than the other way round.
 *
 * The two quantities per ingredient are the point of the screen, and they are
 * different numbers. `grams_raw` is what to buy for the whole session;
 * `grams_cooked_per_portion` is what to weigh into each container. A yield
 * factor separates them — 553.8 g of raw turkey becomes 120 g in each of
 * three boxes — so they are shown in separate columns with separate headings
 * and never summed.
 */
import { Empty, ErrorState, Loading } from "../../components/Status";
import { usePrepPlan } from "../../lib/queries";
import { useSession } from "../../lib/session";

/**
 * Day numbers the way the plan board writes them: 1-based, and collapsed into
 * a range when they run consecutively, which for a batch cook they usually do.
 *
 *   [0, 1, 2]    -> "Дни 1–3"
 *   [0, 2]       -> "Дни 1, 3"
 *   [4]          -> "День 5"
 */
export function formatDays(indexes: readonly number[]): string {
  const days = [...indexes].sort((a, b) => a - b).map((index) => index + 1);
  // Destructured rather than indexed: `noUncheckedIndexedAccess` is on, and
  // a length check does not narrow days[0] for the compiler.
  const [first, ...rest] = days;
  if (first === undefined) return "";
  if (rest.length === 0) return `День ${first}`;

  const runs: string[] = [];
  let start = first;
  let previous = first;

  for (const day of rest) {
    if (day === previous + 1) {
      previous = day;
      continue;
    }
    runs.push(start === previous ? `${start}` : `${start}–${previous}`);
    start = previous = day;
  }
  runs.push(start === previous ? `${start}` : `${start}–${previous}`);

  return `Дни ${runs.join(", ")}`;
}

export function PrepPlan({ planId }: { planId: string }) {
  const { t } = useSession();
  const { data, isLoading, isError, refetch } = usePrepPlan(planId);

  if (isLoading) return <Loading t={t} />;
  if (isError || !data) return <ErrorState t={t} onRetry={() => void refetch()} />;

  if (data.length === 0) {
    return <Empty>В этом плане нет блюд, которые готовятся партией</Empty>;
  }

  return (
    <main className="mx-auto max-w-3xl space-y-4 px-4 py-4">
      <h1 className="text-lg font-semibold">Заготовки</h1>
      <p className="text-sm text-slate-500">
        Что приготовить за один раз и как разложить по контейнерам. Считается из
        плана — чтобы изменить, измените план.
      </p>

      {data.map((session) => (
        <article
          key={session.module_id}
          className="rounded-xl border border-slate-200 bg-white p-4"
        >
          <header className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-semibold">{session.module_name}</h2>
            <p className="text-sm text-slate-500">
              {session.portions} порции · {formatDays(session.day_indexes)}
            </p>
          </header>

          {session.prep_notes && (
            <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">
              {session.prep_notes}
            </p>
          )}

          <table className="mt-3 w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="py-1 font-normal">Ингредиент</th>
                {/* Two headings, because one column is shopping and the other
                    is packing. Labelling either of them just "граммы" is how
                    someone ends up weighing 553 g into one box. */}
                <th className="py-1 text-right font-normal">Купить, сырой вес</th>
                <th className="py-1 text-right font-normal">В контейнер, готовый</th>
              </tr>
            </thead>
            <tbody>
              {session.items.map((item) => (
                <tr key={item.ingredient_id} className="border-b border-slate-100 last:border-0">
                  <td className="py-1">{item.name}</td>
                  {/* Rendered as the strings the API sends. Decimals cross
                      the wire as strings precisely so nothing re-rounds them
                      on the way to a scale. */}
                  <td className="py-1 text-right tabular-nums">{item.grams_raw} г</td>
                  <td className="py-1 text-right tabular-nums">
                    {item.grams_cooked_per_portion} г
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
      ))}
    </main>
  );
}
