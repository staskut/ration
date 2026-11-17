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
import { useSession } from "../../lib/session";

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

function fromIngredient(ingredient: Ingredient, name: string): Draft {
  return {
    name,
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
  if (value.trim() === "") return "Enter a yield";
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return "Not a number";
  if (parsed <= 0 || parsed > MAX_YIELD) return `Must be greater than 0 and at most ${MAX_YIELD}`;
  return undefined;
}

export function IngredientForm({
  editing,
  onDone,
}: {
  editing?: Ingredient;
  onDone: () => void;
}) {
  const { t } = useSession();
  const save = useSaveIngredient();
  const [draft, setDraft] = useState<Draft>(
    editing ? fromIngredient(editing, t.name(editing.names, "")) : emptyDraft(),
  );

  const localYieldError = yieldError(draft.yieldFactor);
  // A field named by the server takes precedence: it knows rules this does not.
  const serverYieldError = save.error?.fieldError("yield_factor")
    ? "The server rejected the yield"
    : undefined;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (localYieldError) return;
    save.mutate(
      {
        id: editing?.id,
        body: {
          // Merged, not replaced. The server swaps the whole names
          // collection for what it is sent, so writing a bare
          // `{ ru: draft.name }` from an English screen would show the
          // planner a Russian name, save their English edit under `ru`,
          // and delete the English name that was already there.
          names: { ...editing?.names, [t.locale]: draft.name },
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
        {editing ? `Edit “${draft.name}”` : "New ingredient"}
      </h2>

      <label className="block">
        <span className="text-sm text-slate-600">Name</span>
        <input
          value={draft.name}
          onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          className="min-h-(--spacing-tap) w-full rounded-lg border border-slate-300 px-2"
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-3">
        <DecimalField
          label="kcal / 100 g"
          value={draft.kcal}
          onChange={(kcal) => setDraft({ ...draft, kcal })}
        />
        <DecimalField
          label="protein / 100 g"
          value={draft.protein}
          onChange={(protein) => setDraft({ ...draft, protein })}
        />
        <DecimalField
          label="Yield"
          value={draft.yieldFactor}
          onChange={(yieldFactor) => setDraft({ ...draft, yieldFactor })}
          error={localYieldError ?? serverYieldError}
          hint="Cooked weight ÷ raw. 1 if eaten as bought"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <DecimalField
          label="Pack size"
          value={draft.packageSize}
          onChange={(packageSize) => setDraft({ ...draft, packageSize })}
          placeholder="optional"
        />
        <label className="block">
          <span className="text-sm text-slate-600">Unit</span>
          <select
            value={draft.packageUnit}
            onChange={(event) => setDraft({ ...draft, packageUnit: event.target.value })}
            className="min-h-(--spacing-tap) w-full rounded-lg border border-slate-300 px-2"
          >
            <option value="">—</option>
            <option value="g">g</option>
            <option value="ml">ml</option>
            <option value="pcs">pcs</option>
          </select>
        </label>
        <label className="block">
          <span className="text-sm text-slate-600">Section</span>
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
          Save
        </button>
        <button
          type="button"
          onClick={onDone}
          className="min-h-(--spacing-tap) rounded-lg border border-slate-300 px-4"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
