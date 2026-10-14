import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { subscribeToPlan } from "./ws";

/** Subscribe while a plan is on screen, and unsubscribe when it is not. */
export function usePlanSocket(planId: string | undefined): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!planId) return;
    const subscription = subscribeToPlan(queryClient, planId);
    return () => subscription.close();
  }, [planId, queryClient]);
}
