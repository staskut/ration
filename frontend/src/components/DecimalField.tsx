/**
 * A decimal input that never becomes a float.
 *
 * `type="number"` would parse the value and reintroduce exactly the rounding
 * the whole system uses Decimal to avoid, at the one boundary where nobody
 * would notice: the value still looks right on screen.
 *
 * The label is associated by id rather than by wrapping, so the accessible
 * name is the label alone. Wrapping would fold the hint and any error text
 * into it, and a field announced as "Yield cooked weight divided by raw 1 if
 * eaten as bought" is worse than no hint at all.
 */
import { useId } from "react";

interface Props {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | undefined;
  hint?: string;
  placeholder?: string;
}

export function DecimalField({ label, value, onChange, error, hint, placeholder }: Props) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  const describedBy = [hint ? hintId : null, error ? errorId : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div>
      <label htmlFor={id} className="text-sm text-slate-600">
        {label}
      </label>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        className={[
          "min-h-(--spacing-tap) w-full rounded-lg border px-2",
          error ? "border-rose-400" : "border-slate-300",
        ].join(" ")}
      />
      {hint && (
        <span id={hintId} className="text-xs text-slate-400">
          {hint}
        </span>
      )}
      {error && (
        <span id={errorId} role="alert" className="block text-xs text-rose-700">
          {error}
        </span>
      )}
    </div>
  );
}
