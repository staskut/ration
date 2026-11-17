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
import {
  useDemoAccess,
  useDemoSignIn,
  useLogin,
  useLogout,
  usePlans,
} from "./lib/queries";
import { useSession } from "./lib/session";

function SignIn() {
  const { t } = useSession();
  const login = useLogin();
  const demo = useDemoAccess();
  const demoSignIn = useDemoSignIn();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const field =
    "min-h-(--spacing-tap) w-full rounded-xl border border-slate-300 px-3";

  return (
    <main className="mx-auto mt-16 max-w-sm px-4 pb-16">
      <h1 className="text-xl font-semibold">Ration</h1>
      {/* A reviewer arriving at a bare pair of fields has no way to know what
          the product is or how to get in. Both belong on this page. */}
      <p className="mt-2 text-sm text-slate-600">{t.t("auth.tagline")}</p>

      {demo.data?.available && (
        <section className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <h2 className="text-sm font-medium">{t.t("auth.demo_heading")}</h2>
          <div className="mt-3 space-y-2">
            {(["planner", "follower"] as const)
              .filter((role) => demo.data?.roles.includes(role))
              .map((role) => (
                <button
                  key={role}
                  type="button"
                  disabled={demoSignIn.isPending}
                  onClick={() => demoSignIn.mutate(role)}
                  className="min-h-(--spacing-tap) w-full rounded-xl bg-slate-900 px-4 text-white disabled:opacity-50"
                >
                  {t.t(role === "planner" ? "auth.demo_planner" : "auth.demo_follower")}
                </button>
              ))}
          </div>
          <p className="mt-3 text-xs text-slate-500">{t.t("auth.demo_fictional")}</p>
        </section>
      )}

      <form
        className="mt-6 space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          login.mutate({ email, password });
        }}
      >
        {demo.data?.available && (
          <p className="text-xs text-slate-400">{t.t("auth.or_sign_in")}</p>
        )}

        {/* Labels, not placeholders. A placeholder is gone the moment there is
            a value in the field, and it is not an accessible name — the fields
            were unreachable by label to anything that navigates by one. */}
        <div>
          <label htmlFor="sign-in-email" className="block text-sm text-slate-600">
            {t.t("auth.email")}
          </label>
          <input
            id="sign-in-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="username"
            className={field}
          />
        </div>

        <div>
          <label htmlFor="sign-in-password" className="block text-sm text-slate-600">
            {t.t("auth.password")}
          </label>
          <input
            id="sign-in-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            className={field}
          />
        </div>

        {login.isError && (
          <p role="alert" className="text-sm text-rose-700">
            {t.t("auth.failed")}
          </p>
        )}
        <button
          type="submit"
          disabled={login.isPending}
          className="min-h-(--spacing-tap) w-full rounded-xl bg-slate-900 text-white disabled:opacity-50"
        >
          {t.t("auth.submit")}
        </button>
      </form>
    </main>
  );
}

/**
 * Who is signed in, and the way out.
 *
 * There was no way to tell which of the two roles you were looking at, and no
 * way to leave — on a shared demo the second of those is the one that traps
 * people.
 */
function AccountBar() {
  const { user, t } = useSession();
  const logout = useLogout();
  if (!user) return null;

  return (
    <div className="flex items-center gap-2 text-xs text-slate-500">
      <span>
        {user.display_name} ·{" "}
        {t.t(user.role === "planner" ? "account.role_planner" : "account.role_follower")}
      </span>
      <button
        type="button"
        onClick={() => logout.mutate()}
        disabled={logout.isPending}
        className="min-h-(--spacing-tap) rounded-lg px-2 underline disabled:opacity-50"
      >
        {t.t("account.sign_out")}
      </button>
    </div>
  );
}

function FollowerApp() {
  const { t } = useSession();
  const [view, setView] = useState<"today" | "shopping">("today");
  const { data: plans } = usePlans();
  const active = plans?.find((plan) => plan.status === "active") ?? plans?.[0];

  return (
    <>
      <header className="flex justify-end px-4 py-2">
        <AccountBar />
      </header>
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
      <nav className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-2">
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
        <div className="ml-auto">
          <AccountBar />
        </div>
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
