import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./index.css";
import { SessionProvider } from "./lib/session";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // The WebSocket invalidates precisely when something changes, so
      // polling on focus would mostly be wasted requests.
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("Root element #root is missing from index.html");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </QueryClientProvider>
  </StrictMode>,
);
