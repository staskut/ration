/**
 * The ingredient catalog.
 *
 * Decimals stay strings end to end. A number input would parse to a float and
 * reintroduce exactly the rounding the whole system uses Decimal to avoid, in
 * the place it would be hardest to notice.
 */
import { useState, type ReactNode } from "react";

import { Empty, ErrorState, Loading } from "../../components/Status";
import {
  useDeleteIngredient,
  useIngredients,
  type Ingredient,
} from "../../lib/queries";
import { type Translator } from "../../lib/i18n";
import { useSession } from "../../lib/session";
import { IngredientForm } from "./IngredientForm";

/**
 * How the ingredient is bought.
 *
 * `package_size` is always a weight — the shopping engine divides raw grams by
 * it to get a package count — and `package_unit` says how the shop counts what
 * that weight comes in. For `pcs` the two together mean "one of these weighs
 * 170 g", so rendering them as "170 pcs" read as a hundred and seventy
 * avocados. They are different facts and they need different sentences.
 */
function packaging(t: Translator, ingredient: Ingredient): string {
  if (!ingredient.package_size) return "—";
  const size = t.grams(ingredient.package_size);
  if (ingredient.package_unit === "pcs") return t.t("catalog.pack_each", { size });
  if (ingredient.package_unit === "ml") return t.t("catalog.pack_ml", { size });
  return t.t("catalog.pack_g", { size });
}

/** One labelled figure on the narrow layout, where there is no column head. */
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-2">
      <dt>{label}</dt>
      <dd className="tabular-nums text-slate-700">{children}</dd>
    </div>
  );
}

/**
 * Visible because the yield factor is the shakiest input in the system and the
 * backlog for measuring it is otherwise invisible (#54).
 */
function Estimated({ t, ingredient }: { t: Translator; ingredient: Ingredient }) {
  if (ingredient.yield_source !== "estimated") return null;
  const note = t.t("catalog.estimated");
  return (
    <span className="ml-1 text-amber-600" title={note} aria-label={note}>
      ≈
    </span>
  );
}

function RowActions({
  t,
  ingredient,
  onEdit,
  onDelete,
}: {
  t: Translator;
  ingredient: Ingredient;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <span className="whitespace-nowrap">
      <button
        type="button"
        onClick={onEdit}
        className="min-h-(--spacing-tap) px-2 text-slate-500 hover:text-slate-900"
      >
        {t.t("catalog.edit")}
      </button>
      <button
        type="button"
        onClick={onDelete}
        className="min-h-(--spacing-tap) px-2 text-slate-400 hover:text-rose-700"
        aria-label={t.t("catalog.delete_named", {
          name: t.name(ingredient.names, ingredient.id),
        })}
      >
        ×
      </button>
    </span>
  );
}

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
        <h1 className="text-xl font-semibold">Ingredients</h1>
        <button
          type="button"
          onClick={() => {
            setEditing(null);
            setCreating(true);
          }}
          className="min-h-(--spacing-tap) rounded-lg bg-slate-900 px-4 text-white"
        >
          Add
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
        placeholder="Search by name or alias"
        className="min-h-(--spacing-tap) w-full rounded-xl border border-slate-300 px-3"
      />

      {remove.isError && (
        // The API refuses to delete an ingredient a module still uses. Showing
        // its message names the module in the way.
        <p role="alert" className="mt-2 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-900">
          {remove.error.message}
        </p>
      )}

      {data?.length === 0 && <Empty>Nothing found</Empty>}

      {/* Two renderings of one row, chosen by width rather than squeezed
          into one. Seven columns at 375 px overlapped to the point of being
          unreadable, and the usual escapes — a horizontal scroller, or
          shrinking the type — both answer "can it be displayed" rather than
          "can it be read". The planner's board may stay desktop-first; the
          catalog is data management, and that happens on whatever is to
          hand. */}
      <ul className="mt-4 space-y-2 sm:hidden">
        {data?.map((ingredient) => (
          <li
            key={ingredient.id}
            className="rounded-xl border border-slate-200 p-3 text-sm"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="font-medium">
                {t.name(ingredient.names, ingredient.id)}
              </span>
              <RowActions
                t={t}
                ingredient={ingredient}
                onEdit={() => {
                  setCreating(false);
                  setEditing(ingredient);
                }}
                onDelete={() => remove.mutate(ingredient.id)}
              />
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-slate-500">
              <Fact label={t.t("catalog.kcal_per_100g")}>
                {t.kcal(ingredient.kcal_per_100g)}
              </Fact>
              <Fact label={t.t("catalog.protein")}>
                {t.grams(ingredient.protein_per_100g)}
              </Fact>
              <Fact label={t.t("catalog.yield")}>
                {t.factor(ingredient.yield_factor)}
                <Estimated t={t} ingredient={ingredient} />
              </Fact>
              <Fact label={t.t("catalog.pack")}>{packaging(t, ingredient)}</Fact>
              <Fact label={t.t("catalog.section")}>
                {t.section(ingredient.shop_section)}
              </Fact>
            </dl>
          </li>
        ))}
      </ul>

      <table className="mt-4 hidden w-full text-sm sm:table">
        <thead className="text-left text-slate-500">
          <tr>
            <th className="py-2">{t.t("catalog.name")}</th>
            <th className="py-2 text-right">{t.t("catalog.kcal_per_100g")}</th>
            <th className="py-2 text-right">{t.t("catalog.protein")}</th>
            <th className="py-2 text-right">{t.t("catalog.yield")}</th>
            <th className="py-2 pr-4 text-right">{t.t("catalog.pack")}</th>
            <th className="py-2">{t.t("catalog.section")}</th>
            <th className="py-2" />
          </tr>
        </thead>
        <tbody>
          {data?.map((ingredient) => (
            <tr key={ingredient.id} className="border-t border-slate-100">
              <td className="py-2">{t.name(ingredient.names, ingredient.id)}</td>
              <td className="py-2 text-right tabular-nums">
                {t.kcal(ingredient.kcal_per_100g)}
              </td>
              <td className="py-2 text-right tabular-nums">
                {t.grams(ingredient.protein_per_100g)}
              </td>
              <td className="py-2 text-right tabular-nums">
                {t.factor(ingredient.yield_factor)}
                <Estimated t={t} ingredient={ingredient} />
              </td>
              <td className="py-2 pr-4 text-right tabular-nums text-slate-500">
                {packaging(t, ingredient)}
              </td>
              <td className="py-2 text-slate-500">{t.section(ingredient.shop_section)}</td>
              <td className="py-2 text-right whitespace-nowrap">
                <RowActions
                  t={t}
                  ingredient={ingredient}
                  onEdit={() => {
                    setCreating(false);
                    setEditing(ingredient);
                  }}
                  onDelete={() => remove.mutate(ingredient.id)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
