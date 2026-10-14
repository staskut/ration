/**
 * Who is signed in, and in which language.
 *
 * The locale comes from the profile rather than the browser: the follower's
 * screens are Russian because the plan is, not because of a device setting.
 */
import { createContext, useContext, type ReactNode } from "react";

import { createTranslator, type Locale, type Translator } from "./i18n";
import { useCurrentUser, type CurrentUser } from "./queries";

interface Session {
  user: CurrentUser | undefined;
  isLoading: boolean;
  isSignedIn: boolean;
  isPlanner: boolean;
  t: Translator;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const { data: user, isLoading } = useCurrentUser();
  const locale = (user?.locale as Locale | undefined) ?? "ru";

  const value: Session = {
    user,
    isLoading,
    isSignedIn: Boolean(user),
    isPlanner: user?.role === "planner",
    t: createTranslator(locale === "en" ? "en" : "ru"),
  };

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside a SessionProvider");
  return session;
}
