/**
 * One tap. No form, no submit button, no confirmation.
 *
 * The real pilot reported liked/not-liked for every module and bloating for
 * none, across a whole week. If recording a rating costs more than a tap, the
 * feedback loop dies the same way section 13 of the reference document did.
 */
import { useRateMeal } from "../../lib/queries";
import type { Translator } from "../../lib/i18n";

type Rating = "liked" | "neutral" | "disliked";

const OPTIONS: Array<{ value: Rating; glyph: string; key: string }> = [
  { value: "liked", glyph: "👍", key: "rate.liked" },
  { value: "neutral", glyph: "😐", key: "rate.neutral" },
  { value: "disliked", glyph: "👎", key: "rate.disliked" },
];

interface Props {
  planId: string;
  entryId: string;
  current: Rating | null;
  t: Translator;
}

export function Rating({ planId, entryId, current, t }: Props) {
  const rate = useRateMeal(planId);

  return (
    <div className="flex gap-2" role="group" aria-label={t.t("rate.liked")}>
      {OPTIONS.map(({ value, glyph, key }) => {
        const selected = current === value;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={selected}
            aria-label={t.t(key)}
            disabled={rate.isPending}
            onClick={() => rate.mutate({ entryId, rating: value })}
            className={[
              "min-h-(--spacing-tap) min-w-(--spacing-tap) rounded-xl border text-xl",
              "transition disabled:opacity-50",
              selected
                ? "border-slate-900 bg-slate-900"
                : "border-slate-200 bg-white hover:border-slate-400",
            ].join(" ")}
          >
            <span aria-hidden>{glyph}</span>
          </button>
        );
      })}
    </div>
  );
}
