import { describe, it, expect, vi, beforeEach } from "vitest";

import { apiRequest, ApiError, setUnauthorizedHandler } from "../src/api/client";

describe("apiRequest", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setUnauthorizedHandler(() => {});
  });

  it("attaches Authorization header when token is provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/x", { token: "abc" });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer abc");
  });

  it("surfaces error envelope as ApiError", async () => {
    const body = JSON.stringify({
      error_code: "unauthorized",
      message: "invalid credentials",
      request_id: "rid-1",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(body, { status: 401 }))
    );

    await expect(apiRequest("/auth/login", { method: "POST", body: {} })).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      errorCode: "unauthorized",
      message: "invalid credentials",
      requestId: "rid-1",
    });
  });

  it("calls the unauthorized handler on 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error_code: "unauthorized", message: "" }), {
          status: 401,
        })
      )
    );

    await expect(apiRequest("/x")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledOnce();
  });
});
