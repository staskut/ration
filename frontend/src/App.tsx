/**
 * Routing splits on role at the root.
 *
 * The planner lands on the plan builder, the follower on Today. They are
 * different products sharing an API, and a shared navigation would make both
 * worse — especially the follower's, whose whole budget is thirty seconds.
 */
import { useState } from "react";

import { ShoppingList } from "./features/follower/ShoppingList";
import { Today } from "./features/follower/Today";
import { Catalog } from "./features/planner/Catalog";
import { ModuleEditor } from "./features/planner/ModuleEditor";
import { PlanBuilder } from "./features/planner/PlanBuilder";
import { PrepPlan } from "./features/planner/PrepPlan";
import { Loading } from "./components/Status";
import { useLogin, usePlans } from "./lib/queries";
import { useSession } from "./lib/session";

function SignIn() {
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  return (
    <main className="mx-auto mt-24 max-w-sm px-4">
      <h1 className="text-xl font-semibold">Ration</h1>
      <form
        className="mt-4 space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          login.mutate({ email, password });
        }}
      >
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="Почта"
          autoComplete="username"
          className="min-h-(--spacing-tap) w-full rounded-xl border border-slate-300 px-3"
        />
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Пароль"
          autoComplete="current-password"
          className="min-h-(--spacing-tap) w-full rounded-xl border border-slate-300 px-3"
        />
        {login.isError && (
          <p role="alert" className="text-sm text-rose-700">
            Почта или пароль неверны
          </p>
        )}
        <button
          type="submit"
          disabled={login.isPending}
          className="min-h-(--spacing-tap) w-full rounded-xl bg-slate-900 text-white disabled:opacity-50"
        >
          Войти
        </button>
      </form>
    </main>
  );
}

function FollowerApp() {
  const { t } = useSession();
  const [view, setView] = useState<"today" | "shopping">("today");
  const { data: plans } = usePlans();
  const active = plans?.find((plan) => plan.status === "active") ?? plans?.[0];

  return (
    <>
      {view === "today" ? (
        <Today />
      ) : active ? (
        <ShoppingList planId={active.id} />
      ) : (
        <Loading t={t} />
      )}

      {/* Two destinations, so a tab bar rather than a menu: one tap, no
          navigation to learn. */}
      <nav className="fixed inset-x-0 bottom-0 grid grid-cols-2 border-t border-slate-200 bg-white">
        {(["today", "shopping"] as const).map((target) => (
          <button
            key={target}
            type="button"
            onClick={() => setView(target)}
            aria-current={view === target}
            className={`min-h-(--spacing-tap) py-3 text-sm ${
              view === target ? "font-semibold" : "text-slate-500"
            }`}
          >
            {target === "today" ? t.t("today.title") : t.t("shopping.title")}
          </button>
        ))}
      </nav>
    </>
  );
}

function PlannerApp() {
  const [view, setView] = useState<"plan" | "prep" | "modules" | "catalog">("plan");
  const { data: plans } = usePlans();
  const active = plans?.find((plan) => plan.status === "active") ?? plans?.[0];
  const { t } = useSession();

  return (
    <>
      <nav className="flex gap-2 border-b border-slate-200 px-4 py-2">
        <button
          type="button"
          onClick={() => setView("plan")}
          className={view === "plan" ? "font-semibold" : "text-slate-500"}
        >
          Plan
        </button>
        <button
          type="button"
          onClick={() => setView("prep")}
          className={view === "prep" ? "font-semibold" : "text-slate-500"}
        >
          Prep
        </button>
        <button
          type="button"
          onClick={() => setView("modules")}
          className={view === "modules" ? "font-semibold" : "text-slate-500"}
        >
          Modules
        </button>
        <button
          type="button"
          onClick={() => setView("catalog")}
          className={view === "catalog" ? "font-semibold" : "text-slate-500"}
        >
          Ingredients
        </button>
      </nav>
      {view === "catalog" ? (
        <Catalog />
      ) : view === "modules" ? (
        <ModuleEditor />
      ) : !active ? (
        <Loading t={t} />
      ) : view === "prep" ? (
        <PrepPlan planId={active.id} />
      ) : (
        <PlanBuilder planId={active.id} />
      )}
    </>
  );
}

export function App() {
  const { isLoading, isSignedIn, isPlanner, t } = useSession();

  if (isLoading) return <Loading t={t} />;
  if (!isSignedIn) return <SignIn />;
  return isPlanner ? <PlannerApp /> : <FollowerApp />;
}
