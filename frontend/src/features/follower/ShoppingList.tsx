/**
 * A shopping list that works in one hand, in a shop.
 *
 * Staples are collapsed because section 12's quantities for them are "buy a
 * bottle" rather than anything the plan computed, and a list that mixes
 * "553.8 g turkey" with "about 30 g of olive oil" trains you to ignore both.
 */
import { useMemo, useState } from "react";

import { ErrorState, Loading } from "../../components/Status";
import { useSetChecked, useShoppingList, type ShoppingList as List } from "../../lib/queries";
import { useSession } from "../../lib/session";
import { usePlanSocket } from "../../lib/usePlanSocket";

type Line = List["lines"][number];

function Item({
  line,
  onToggle,
}: {
  line: Line;
  onToggle: (id: string, checked: boolean) => void;
}) {
  const { t } = useSession();
  const amount =
    line.packages != null && line.package_unit === "pcs"
      ? `${line.packages} шт`
      : `${t.number(line.purchase_amount)} г`;

  return (
    <li>
      <button
        type="button"
        onClick={() => onToggle(line.ingredient_id, !line.checked)}
        aria-pressed={line.checked}
        className={[
          "flex min-h-(--spacing-tap) w-full items-center gap-3 rounded-xl px-3 py-2 text-left",
          line.checked ? "opacity-40" : "",
        ].join(" ")}
      >
        <span
          aria-hidden
          className={[
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-md border",
            line.checked ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300",
          ].join(" ")}
        >
          {line.checked ? "✓" : ""}
        </span>
        <span className="min-w-0 flex-1">
          <span className={line.checked ? "line-through" : ""}>{line.name}</span>
          {line.size_is_critical && (
            // The pilot's one real failure: 45 g flatbreads bought against a
            // 75 g spec. The constraint has to reach the person in the shop.
            <span className="ml-2 rounded bg-rose-100 px-1.5 py-0.5 text-xs text-rose-800">
              {t.t("shopping.critical")}
            </span>
          )}
        </span>
        <span className="shrink-0 tabular-nums text-slate-600">{amount}</span>
      </button>
    </li>
  );
}

export function ShoppingList({ planId }: { planId: string }) {
  const { t } = useSession();
  const { data, isLoading, isError, refetch } = useShoppingList(planId);
  const setChecked = useSetChecked(planId);
  const [staplesOpen, setStaplesOpen] = useState(false);

  usePlanSocket(planId);

  const grouped = useMemo(() => {
    const sections = new Map<string, Line[]>();
    const staples: Line[] = [];
    for (const line of data?.lines ?? []) {
      if (line.is_staple) {
        staples.push(line);
        continue;
      }
      const existing = sections.get(line.shop_section) ?? [];
      existing.push(line);
      sections.set(line.shop_section, existing);
    }
    return { sections: [...sections.entries()], staples };
  }, [data]);

  if (isLoading) return <Loading t={t} />;
  if (isError || !data) return <ErrorState t={t} onRetry={() => void refetch()} />;

  const countable = data.lines.filter((line) => !line.is_staple);
  const done = countable.filter((line) => line.checked).length;

  const toggle = (ingredientId: string, checked: boolean) =>
    setChecked.mutate({ ingredientId, checked });

  return (
    <main className="mx-auto max-w-xl px-4 pb-16">
      <header className="sticky top-0 bg-white/95 py-3 backdrop-blur">
        <h1 className="text-lg font-semibold">{t.t("shopping.title")}</h1>
        <p className="text-sm text-slate-500">
          {t.t("shopping.progress", { done, total: countable.length })}
        </p>
      </header>

      {grouped.sections.map(([section, lines]) => (
        <section key={section} className="mt-4">
          <h2 className="px-3 text-sm font-medium text-slate-500">{t.section(section)}</h2>
          <ul className="mt-1">
            {lines.map((line) => (
              <Item key={line.ingredient_id} line={line} onToggle={toggle} />
            ))}
          </ul>
        </section>
      ))}

      {grouped.staples.length > 0 && (
        <section className="mt-6">
          <button
            type="button"
            onClick={() => setStaplesOpen((open) => !open)}
            aria-expanded={staplesOpen}
            className="min-h-(--spacing-tap) w-full rounded-xl bg-slate-50 px-3 text-left text-sm text-slate-600"
          >
            {staplesOpen ? "▾" : "▸"} {t.t("shopping.staples")} ({grouped.staples.length})
          </button>
          {staplesOpen && (
            <ul className="mt-1">
              {grouped.staples.map((line) => (
                <Item key={line.ingredient_id} line={line} onToggle={toggle} />
              ))}
            </ul>
          )}
        </section>
      )}
    </main>
  );
}
