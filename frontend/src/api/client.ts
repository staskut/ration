/**
 * The only place a network call is made.
 *
 * Hand-written, but thin: everything it knows about the API's shape comes from
 * `types.ts`, which is generated from `openapi.yaml`. CI regenerates and diffs,
 * so the contract and this file cannot drift apart silently.
 *
 * Nothing outside `src/lib/queries.ts` may import from this directory. A lint
 * rule enforces that; see docs/decisions.md D6.
 */
import type { paths } from "./types";

export const API_BASE = "/api";

/** The shared error envelope every endpoint returns. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Array<{ field?: string; code: string }>;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Array<{ field?: string; code: string }>;

  constructor(status: number, body: ApiErrorBody | null, fallback: string) {
    super(body?.error.message ?? fallback);
    this.name = "ApiError";
    this.status = status;
    this.code = body?.error.code ?? "UNKNOWN";
    this.details = body?.error.details ?? [];
  }

  /** The validation message for one field, if the server named it. */
  fieldError(field: string): string | undefined {
    return this.details.find((d) => d.field === field)?.code;
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${API_BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const search = params.toString();
  return search ? `${url}?${search}` : url;
}

async function request<T>(
  method: Method,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const response = await fetch(buildUrl(path, options.query), {
    method,
    // The session is an HttpOnly cookie, so it only travels if this is set.
    // Without it every request is anonymous and every screen shows a login.
    credentials: "include",
    headers: options.body === undefined ? {} : { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // A non-JSON error body — a proxy timeout, say. The status still carries.
    }
    throw new ApiError(response.status, body, response.statusText);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PUT", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, { ...options, body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>("DELETE", path, options),
};

/** Response and body types, named from the generated paths. */
export type Schema<K extends keyof Components> = Components[K];
type Components = NonNullable<
  paths["/ingredients"]["get"]["responses"][200]["content"]["application/json"][number]
> extends infer _I
  ? {
      Ingredient: paths["/ingredients"]["get"]["responses"][200]["content"]["application/json"][number];
      Module: paths["/modules"]["get"]["responses"][200]["content"]["application/json"][number];
      Profile: paths["/profiles/{profileId}"]["get"]["responses"][200]["content"]["application/json"];
      Plan: paths["/plans/{planId}"]["get"]["responses"][200]["content"]["application/json"];
      PlanSummary: paths["/plans"]["get"]["responses"][200]["content"]["application/json"][number];
      ValidationReport: paths["/plans/{planId}/validation"]["get"]["responses"][200]["content"]["application/json"];
      ShoppingList: paths["/plans/{planId}/shopping-list"]["get"]["responses"][200]["content"]["application/json"];
      CookSession: paths["/plans/{planId}/prep-plan"]["get"]["responses"][200]["content"]["application/json"][number];
      TodayView: paths["/today"]["get"]["responses"][200]["content"]["application/json"];
      CurrentUser: paths["/auth/me"]["get"]["responses"][200]["content"]["application/json"];
      DemoAccess: paths["/auth/demo"]["get"]["responses"][200]["content"]["application/json"];
    }
  : never;
