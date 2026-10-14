/**
 * Loading, error and empty states.
 *
 * Separate components rather than inline ternaries because every screen needs
 * all three, and an empty state rendered as nothing is indistinguishable from
 * a screen that failed to load.
 */
import type { ReactNode } from "react";

import type { Translator } from "../lib/i18n";

export function Loading({ t }: { t: Translator }) {
  return (
    <div className="p-6 text-center text-slate-500" role="status" aria-live="polite">
      {t.t("common.loading")}
    </div>
  );
}

export function ErrorState({ t, onRetry }: { t: Translator; onRetry?: () => void }) {
  return (
    <div className="p-6 text-center" role="alert">
      <p className="text-slate-700">{t.t("common.error")}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 min-h-(--spacing-tap) rounded-lg bg-slate-900 px-4 text-white"
        >
          {t.t("common.retry")}
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-4 py-8 text-center text-slate-400">{children}</p>;
}
