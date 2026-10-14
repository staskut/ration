/**
 * The ingredient catalog.
 *
 * Decimals stay strings end to end. A number input would parse to a float and
 * reintroduce exactly the rounding the whole system uses Decimal to avoid, in
 * the place it would be hardest to notice.
 */
import { useState } from "react";

import { Empty, ErrorState, Loading } from "../../components/Status";
import {
  useDeleteIngredient,
  useIngredients,
  type Ingredient,
} from "../../lib/queries";
import { useSession } from "../../lib/session";
import { IngredientForm } from "./IngredientForm";

export function Catalog() {
  const { t } = useSession();
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Ingredient | null>(null);
  const [creating, setCreating] = useState(false);
  const { data, isLoading, isError, refetch } = useIngredients(search);
  const remove = useDeleteIngredient();

  if (isLoading) return <Loading t={t} />;
  if (isError) return <ErrorState t={t} onRetry={() => void refetch()} />;

  return (
    <main className="mx-auto max-w-5xl px-4 pb-16">
      <div className="flex items-center justify-between py-4">
        <h1 className="text-xl font-semibold">Ингредиенты</h1>
        <button
          type="button"
          onClick={() => {
            setEditing(null);
            setCreating(true);
          }}
          className="min-h-(--spacing-tap) rounded-lg bg-slate-900 px-4 text-white"
        >
          Добавить
        </button>
      </div>

      {(creating || editing) && (
        <div className="mb-4">
          <IngredientForm
            {...(editing ? { editing } : {})}
            onDone={() => {
              setCreating(false);
              setEditing(null);
            }}
          />
        </div>
      )}

      <input
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Поиск по названию или синониму"
        className="min-h-(--spacing-tap) w-full rounded-xl border border-slate-300 px-3"
      />

      {remove.isError && (
        // The API refuses to delete an ingredient a module still uses. Showing
        // its message names the module in the way.
        <p role="alert" className="mt-2 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-900">
          {remove.error.message}
        </p>
      )}

      {data?.length === 0 && <Empty>Ничего не найдено</Empty>}

      <table className="mt-4 w-full text-sm">
        <thead className="text-left text-slate-500">
          <tr>
            <th className="py-2">Название</th>
            <th className="py-2 text-right">ккал/100 г</th>
            <th className="py-2 text-right">белок</th>
            <th className="py-2 text-right">выход</th>
            <th className="py-2 text-right">упаковка</th>
            <th className="py-2">раздел</th>
            <th className="py-2" />
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
                    title="Оценка, не измерение. Готовый вес ÷ сырой"
                    aria-label="Оценка, не измерение"
                  >
                    ≈
                  </span>
                )}
              </td>
              <td className="py-2 text-right tabular-nums text-slate-500">
                {ingredient.package_size
                  ? `${t.number(ingredient.package_size)} ${ingredient.package_unit ?? ""}`
                  : "—"}
              </td>
              <td className="py-2 text-slate-500">{t.section(ingredient.shop_section)}</td>
              <td className="py-2 text-right whitespace-nowrap">
                <button
                  type="button"
                  onClick={() => {
                    setCreating(false);
                    setEditing(ingredient);
                  }}
                  className="px-2 text-slate-500 hover:text-slate-900"
                >
                  Изменить
                </button>
                <button
                  type="button"
                  onClick={() => remove.mutate(ingredient.id)}
                  className="px-2 text-slate-400 hover:text-rose-700"
                  aria-label={`Удалить ${ingredient.names.ru ?? ingredient.id}`}
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
