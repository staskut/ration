import { describe, expect, it, vi, afterEach } from "vitest";

import { ApiError, api } from "../../src/api/client";

function calls(): unknown[][] {
  return (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls as unknown[][];
}

function firstCall(): { url: string; init: RequestInit } {
  const call = calls()[0];
  if (!call) throw new Error("fetch was never called");
  return { url: call[0] as string, init: (call[1] ?? {}) as RequestInit };
}

function respondWith(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(body === undefined ? null : JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the api client", () => {
  it("sends credentials, or the session cookie never travels", async () => {
    respondWith(200, { ok: true });
    await api.get("/auth/me");
    expect(firstCall().init.credentials).toBe("include");
  });

  it("prefixes every path with /api", async () => {
    respondWith(200, []);
    await api.get("/ingredients");
    expect(firstCall().url).toBe("/api/ingredients");
  });

  it("drops undefined query parameters rather than sending the string", async () => {
    respondWith(200, []);
    await api.get("/ingredients", { query: { q: undefined, section: "dairy" } });
    expect(firstCall().url).toBe("/api/ingredients?section=dairy");
  });

  it("throws a typed error carrying the server's code", async () => {
    respondWith(409, {
      error: { code: "ALIAS_IN_USE", message: "already taken", details: [] },
    });
    await expect(api.post("/ingredients", {})).rejects.toSatisfy(
      (error: unknown) =>
        error instanceof ApiError &&
        error.code === "ALIAS_IN_USE" &&
        error.status === 409,
    );
  });

  it("names the offending field when the server did", async () => {
    respondWith(422, {
      error: {
        code: "VALIDATION_FAILED",
        message: "bad",
        details: [{ field: "yield_factor", code: "out_of_range" }],
      },
    });
    try {
      await api.post("/ingredients", {});
      expect.unreachable("should have thrown");
    } catch (error) {
      expect((error as ApiError).fieldError("yield_factor")).toBe("out_of_range");
      expect((error as ApiError).fieldError("nothing")).toBeUndefined();
    }
  });

  it("survives a non-JSON error body", async () => {
    // A proxy timeout returns HTML. The status still has to reach the caller.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>504</html>", { status: 504 })),
    );
    await expect(api.get("/plans")).rejects.toSatisfy(
      (error: unknown) => error instanceof ApiError && error.status === 504,
    );
  });

  it("returns undefined for a 204 rather than failing to parse", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    await expect(api.post("/auth/logout")).resolves.toBeUndefined();
  });
});
