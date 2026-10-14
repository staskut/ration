/**
 * Compose a module and watch its totals.
 *
 * Totals are never computed here. The server derives them from the lines, and
 * a second implementation in the browser would disagree with it eventually —
 * with the shopping list using one number and the planner reading another.
 * So they are read-only and refresh after a save.
 */
import { useState } from "react";

import { DecimalField } from "../../components/DecimalField";
import { Loading } from "../../components/Status";
import {
  useIngredients,
  useModules,
  useSaveModule,
  type Module,
} from "../../lib/queries";
import { useSession } from "../../lib/session";

const SLOTS = ["breakfast", "lunch", "snack", "dinner", "treat"] as const;
const ROLES = ["main", "side"] as const;

interface LineDraft {
  ingredient_id: string;
  grams_cooked: string;
  size_is_critical: boolean;
}

interface Draft {
  name: string;
  slot: string;
  role: string;
  batch: string;
  tags: string;
  prepNotes: string;
  lines: LineDraft[];
}

function toDraft(module?: Module): Draft {
  if (!module) {
    return {
      name: "", slot: "dinner", role: "main", batch: "1",
      tags: "", prepNotes: "", lines: [],
    };
  }
  return {
    name: module.name,
    slot: module.slot,
    role: module.role,
    batch: String(module.batch_portions),
    tags: module.tags.join(", "),
    prepNotes: module.prep_notes ?? "",
    lines: module.lines.map((line) => ({
      ingredient_id: line.ingredient_id,
      grams_cooked: line.grams_cooked,
      size_is_critical: line.size_is_critical ?? false,
    })),
  };
}

function move<T>(items: T[], from: number, to: number): T[] {
  if (to < 0 || to >= items.length) return items;
  const next = [...items];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved!);
  return next;
}

export function ModuleEditor() {
  const { t } = useSession();
  const { data: modules, isLoading } = useModules();
  const { data: ingredients } = useIngredients();
  const save = useSaveModule();

  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(() => toDraft());

  if (isLoading) return <Loading t={t} />;

  const editing = modules?.find((module) => module.id === selected);
  const noLines = draft.lines.length === 0;

  const choose = (module: Module | null) => {
    setSelected(module?.id ?? null);
    setDraft(toDraft(module ?? undefined));
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (noLines) return;
    save.mutate({
      ...(selected ? { id: selected } : {}),
      body: {
        name: draft.name,
        slot: draft.slot,
        role: draft.role,
        batch_portions: Number(draft.batch),
        prep_notes: draft.prepNotes || null,
        tags: draft.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
        lines: draft.lines.map((line) => ({
          ingredient_id: line.ingredient_id,
          grams_cooked: line.grams_cooked,
          size_is_critical: line.size_is_critical,
        })),
      },
    });
  };

  return (
    <main className="mx-auto grid max-w-6xl gap-4 px-4 pb-16 lg:grid-cols-[18rem_1fr]">
      <aside>
        <div className="flex items-center justify-between py-4">
          <h1 className="text-xl font-semibold">Модули</h1>
          <button
            type="button"
            onClick={() => choose(null)}
            className="min-h-(--spacing-tap) rounded-lg bg-slate-900 px-3 text-sm text-white"
          >
            Новый
          </button>
        </div>
        <ul className="space-y-1">
          {modules?.map((module) => (
            <li key={module.id}>
              <button
                type="button"
                onClick={() => choose(module)}
                aria-current={selected === module.id}
                className={[
                  "w-full rounded-lg px-3 py-2 text-left text-sm",
                  selected === module.id ? "bg-slate-900 text-white" : "hover:bg-slate-100",
                ].join(" ")}
              >
                <span className="block truncate">{module.name}</span>
                <span className="text-xs opacity-70">
                  {t.slot(module.slot)} · {t.number(module.kcal)} ккал ·{" "}
                  {t.number(module.protein_g)} г
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <form onSubmit={submit} className="space-y-4 py-4">
        {/* Read-only, from the server. Two implementations of the same
            arithmetic disagree eventually, and the server's is the one the
            shopping list uses. */}
        {editing && (
          <p className="rounded-xl bg-slate-50 px-4 py-3 text-sm">
            <strong>{t.number(editing.kcal)} ккал</strong> ·{" "}
            <strong>{t.number(editing.protein_g)} г белка</strong>
            <span className="ml-2 text-slate-400">считает сервер</span>
          </p>
        )}

        <label className="block">
          <span className="text-sm text-slate-600">Название</span>
          <input
            value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            className="min-h-(--spacing-tap) w-full rounded-lg border border-slate-300 px-2"
          />
        </label>

        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className="text-sm text-slate-600">Приём пищи</span>
            <select
              value={draft.slot}
              onChange={(event) => setDraft({ ...draft, slot: event.target.value })}
              className="min-h-(--spacing-tap) w-full rounded-lg border border-slate-300 px-2"
            >
              {SLOTS.map((slot) => (
                <option key={slot} value={slot}>{t.slot(slot)}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-sm text-slate-600">Роль</span>
            <select
              value={draft.role}
              onChange={(event) => setDraft({ ...draft, role: event.target.value })}
              className="min-h-(--spacing-tap) w-full rounded-lg border border-slate-300 px-2"
            >
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {role === "main" ? "основное" : "гарнир"}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-sm text-slate-600">Порций за раз</span>
            <input
              type="number"
              min={1}
              max={7}
              value={draft.batch}
              onChange={(event) => setDraft({ ...draft, batch: event.target.value })}
              className="min-h-(--spacing-tap) w-full rounded-lg border border-slate-300 px-2"
            />
          </label>
        </div>

        <section>
          <h2 className="text-sm font-medium text-slate-600">Состав, готовый вес</h2>
          {noLines && (
            <p className="mt-1 text-sm text-rose-700">
              Нужен хотя бы один ингредиент
            </p>
          )}
          <ul className="mt-2 space-y-2">
            {draft.lines.map((line, index) => (
              <li key={index} className="flex flex-wrap items-end gap-2">
                <select
                  value={line.ingredient_id}
                  onChange={(event) => {
                    const lines = [...draft.lines];
                    lines[index] = { ...line, ingredient_id: event.target.value };
                    setDraft({ ...draft, lines });
                  }}
                  className="min-h-(--spacing-tap) flex-1 rounded-lg border border-slate-300 px-2"
                >
                  {ingredients?.map((ingredient) => (
                    <option key={ingredient.id} value={ingredient.id}>
                      {ingredient.names.ru ?? ingredient.id}
                    </option>
                  ))}
                </select>
                <div className="w-28">
                  <DecimalField
                    label="г"
                    value={line.grams_cooked}
                    onChange={(grams) => {
                      const lines = [...draft.lines];
                      lines[index] = { ...line, grams_cooked: grams };
                      setDraft({ ...draft, lines });
                    }}
                  />
                </div>
                <label className="flex min-h-(--spacing-tap) items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={line.size_is_critical}
                    onChange={(event) => {
                      const lines = [...draft.lines];
                      lines[index] = { ...line, size_is_critical: event.target.checked };
                      setDraft({ ...draft, lines });
                    }}
                  />
                  {/* The pilot bought 45 g flatbreads for a 75 g module. */}
                  важен размер
                </label>
                <button
                  type="button"
                  aria-label="Выше"
                  onClick={() => setDraft({ ...draft, lines: move(draft.lines, index, index - 1) })}
                  className="min-h-(--spacing-tap) px-2 text-slate-400"
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label="Ниже"
                  onClick={() => setDraft({ ...draft, lines: move(draft.lines, index, index + 1) })}
                  className="min-h-(--spacing-tap) px-2 text-slate-400"
                >
                  ↓
                </button>
                <button
                  type="button"
                  aria-label="Убрать"
                  onClick={() =>
                    setDraft({ ...draft, lines: draft.lines.filter((_, i) => i !== index) })
                  }
                  className="min-h-(--spacing-tap) px-2 text-slate-400 hover:text-rose-700"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() =>
              setDraft({
                ...draft,
                lines: [
                  ...draft.lines,
                  {
                    ingredient_id: ingredients?.[0]?.id ?? "",
                    grams_cooked: "100",
                    size_is_critical: false,
                  },
                ],
              })
            }
            className="mt-2 min-h-(--spacing-tap) rounded-lg border border-dashed border-slate-300 px-3 text-sm text-slate-500"
          >
            + ингредиент
          </button>
        </section>

        <label className="block">
          <span className="text-sm text-slate-600">Метки, через запятую</span>
          <input
            value={draft.tags}
            onChange={(event) => setDraft({ ...draft, tags: event.target.value })}
            className="min-h-(--spacing-tap) w-full rounded-lg border border-slate-300 px-2"
          />
        </label>

        <label className="block">
          <span className="text-sm text-slate-600">Заметки к приготовлению</span>
          <textarea
            value={draft.prepNotes}
            onChange={(event) => setDraft({ ...draft, prepNotes: event.target.value })}
            rows={2}
            className="w-full rounded-lg border border-slate-300 p-2"
          />
        </label>

        {save.isError && (
          <p role="alert" className="text-sm text-rose-700">{save.error.message}</p>
        )}

        <button
          type="submit"
          disabled={save.isPending || noLines}
          className="min-h-(--spacing-tap) rounded-lg bg-slate-900 px-4 text-white disabled:opacity-50"
        >
          Сохранить
        </button>
      </form>
    </main>
  );
}
