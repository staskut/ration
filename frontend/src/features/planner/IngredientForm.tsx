/**
 * Create or edit an ingredient.
 *
 * Every numeric field is a text input carrying a string end to end. The
 * yield factor is validated here as well as on the server, so the planner
 * learns before submitting rather than after.
 */
import { useState } from "react";

import { DecimalField } from "../../components/DecimalField";
import { useSaveIngredient, type Ingredient } from "../../lib/queries";

const SECTIONS = [
  "meat_fish", "dairy", "produce", "fruit", "grains",
  "nuts_pastes", "oils_sauces", "supplements", "treats", "other",
] as const;

const MAX_YIELD = 5;

interface Draft {
  name: string;
  kcal: string;
  protein: string;
  yieldFactor: string;
  packageSize: string;
  packageUnit: string;
  section: string;
}

function emptyDraft(): Draft {
  return {
    name: "", kcal: "", protein: "", yieldFactor: "1",
    packageSize: "", packageUnit: "", section: "other",
  };
}

function fromIngredient(ingredient: Ingredient): Draft {
  return {
    name: ingredient.names.ru ?? "",
    kcal: ingredient.kcal_per_100g,
    protein: ingredient.protein_per_100g,
    yieldFactor: ingredient.yield_factor,
    packageSize: ingredient.package_size ?? "",
    packageUnit: ingredient.package_unit ?? "",
    section: ingredient.shop_section,
  };
}

/** Mirrors the server's bound so the planner is told before submitting. */
export function yieldError(value: string): string | undefined {
  if (value.trim() === "") return "Укажите выход";
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return "Не число";
  if (parsed <= 0 || parsed > MAX_YIELD) return `Должен быть больше 0 и не больше ${MAX_YIELD}`;
  return undefined;
}

export function IngredientForm({
  editing,
  onDone,
}: {
  editing?: Ingredient;
  onDone: () => void;
}) {
  const save = useSaveIngredient();
  const [draft, setDraft] = useState<Draft>(
    editing ? fromIngredient(editing) : emptyDraft(),
  );

  const localYieldError = yieldError(draft.yieldFactor);
  // A field named by the server takes precedence: it knows rules this does not.
  const serverYieldError = save.error?.fieldError("yield_factor")
    ? "Сервер отклонил выход"
    : undefined;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (localYieldError) return;
    save.mutate(
      {
        id: editing?.id,
        body: {
          names: { ru: draft.name },
          kcal_per_100g: draft.kcal,
          protein_per_100g: draft.protein,
          yield_factor: draft.yieldFactor,
          yield_source: draft.yieldFactor === "1" ? "as_purchased" : "estimated",
          package_size: draft.packageSize || null,
          package_unit: draft.packageUnit || null,
          shop_section: draft.section,
        },
      },
      { onSuccess: onDone },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-3 rounded-2xl border border-slate-200 p-4">
      <h2 className="font-medium">
        {editing ? `Изменить «${draft.name}»` : "Новый ингредиент"}
      </h2>

      <label className="block">
        <span className="text-sm text-slate-600">Название</span>
        <input
          value={draft.name}
          onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          className="min-h-(--spacing-tap) w-full rounded-lg border border-slate-300 px-2"
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-3">
        <DecimalField
          label="ккал / 100 г"
          value={draft.kcal}
          onChange={(kcal) => setDraft({ ...draft, kcal })}
        />
        <DecimalField
          label="белок / 100 г"
          value={draft.protein}
          onChange={(protein) => setDraft({ ...draft, protein })}
        />
        <DecimalField
          label="Выход"
          value={draft.yieldFactor}
          onChange={(yieldFactor) => setDraft({ ...draft, yieldFactor })}
          error={localYieldError ?? serverYieldError}
          hint="Готовый вес ÷ сырой. 1 — если едят как есть"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <DecimalField
          label="Размер упаковки"
          value={draft.packageSize}
          onChange={(packageSize) => setDraft({ ...draft, packageSize })}
          placeholder="необязательно"
        />
        <label className="block">
          <span className="text-sm text-slate-600">Единица</span>
          <select
            value={draft.packageUnit}
            onChange={(event) => setDraft({ ...draft, packageUnit: event.target.value })}
            className="min-h-(--spacing-tap) w-full rounded-lg border border-slate-300 px-2"
          >
            <option value="">—</option>
            <option value="g">г</option>
            <option value="ml">мл</option>
            <option value="pcs">шт</option>
          </select>
        </label>
        <label className="block">
          <span className="text-sm text-slate-600">Раздел</span>
          <select
            value={draft.section}
            onChange={(event) => setDraft({ ...draft, section: event.target.value })}
            className="min-h-(--spacing-tap) w-full rounded-lg border border-slate-300 px-2"
          >
            {SECTIONS.map((section) => (
              <option key={section} value={section}>
                {section}
              </option>
            ))}
          </select>
        </label>
      </div>

      {save.isError && !serverYieldError && (
        <p role="alert" className="text-sm text-rose-700">
          {save.error.message}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={save.isPending || Boolean(localYieldError)}
          className="min-h-(--spacing-tap) rounded-lg bg-slate-900 px-4 text-white disabled:opacity-50"
        >
          Сохранить
        </button>
        <button
          type="button"
          onClick={onDone}
          className="min-h-(--spacing-tap) rounded-lg border border-slate-300 px-4"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}
