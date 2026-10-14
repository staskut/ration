/**
 * The ingredient catalog.
 *
 * Decimals stay strings end to end. A number input would parse to a float and
 * reintroduce exactly the rounding the whole system uses Decimal to avoid, in
 * the place it would be hardest to notice.
 */
import { useState } from "react";

import { Empty, ErrorState, Loading } from "../../components/Status";
import { useIngredients } from "../../lib/queries";
import { useSession } from "../../lib/session";

export function Catalog() {
  const { t } = useSession();
  const [search, setSearch] = useState("");
  const { data, isLoading, isError, refetch } = useIngredients(search);

  if (isLoading) return <Loading t={t} />;
  if (isError) return <ErrorState t={t} onRetry={() => void refetch()} />;

  return (
    <main className="mx-auto max-w-4xl px-4 pb-16">
      <h1 className="py-4 text-xl font-semibold">Ингредиенты</h1>

      <input
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Поиск по названию или синониму"
        className="min-h-(--spacing-tap) w-full rounded-xl border border-slate-300 px-3"
      />

      {data?.length === 0 && <Empty>Ничего не найдено</Empty>}

      <table className="mt-4 w-full text-sm">
        <thead className="text-left text-slate-500">
          <tr>
            <th className="py-2">Название</th>
            <th className="py-2 text-right">ккал/100 г</th>
            <th className="py-2 text-right">белок</th>
            <th className="py-2 text-right">выход</th>
            <th className="py-2">раздел</th>
          </tr>
        </thead>
        <tbody>
          {data?.map((ingredient) => (
            <tr key={ingredient.id} className="border-t border-slate-100">
              <td className="py-2">{ingredient.names.ru ?? ingredient.id}</td>
              <td className="py-2 text-right tabular-nums">
                {t.number(ingredient.kcal_per_100g)}
              </td>
              <td className="py-2 text-right tabular-nums">
                {t.number(ingredient.protein_per_100g)}
              </td>
              <td className="py-2 text-right tabular-nums">
                {t.number(ingredient.yield_factor)}
                {ingredient.yield_source === "estimated" && (
                  // Visible because it is the shakiest input in the system and
                  // the backlog for fixing it is otherwise invisible (#54).
                  <span
                    className="ml-1 text-amber-600"
                    title="Оценка, не измерение"
                    aria-label="Оценка, не измерение"
                  >
                    ≈
                  </span>
                )}
              </td>
              <td className="py-2 text-slate-500">{t.section(ingredient.shop_section)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
