import { describe, it, expect, vi, beforeEach } from "vitest";

import { useAuthStore } from "../src/store/auth";

describe("useAuthStore", () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      username: null,
      loginError: null,
      isLoggingIn: false,
    });
    vi.restoreAllMocks();
  });

  it("login stores token and username on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ access_token: "tok-123", token_type: "bearer" }),
          { status: 200 }
        )
      )
    );

    await useAuthStore.getState().login("alice", "secret123");

    const s = useAuthStore.getState();
    expect(s.token).toBe("tok-123");
    expect(s.username).toBe("alice");
    expect(s.loginError).toBeNull();
  });

  it("login records error on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error_code: "unauthorized", message: "invalid credentials" }),
          { status: 401 }
        )
      )
    );

    await expect(useAuthStore.getState().login("alice", "wrong")).rejects.toBeDefined();

    const s = useAuthStore.getState();
    expect(s.token).toBeNull();
    expect(s.loginError).toMatch(/invalid credentials/);
  });

  it("logout clears token", () => {
    useAuthStore.setState({ token: "tok", username: "alice" });
    useAuthStore.getState().logout();
    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().username).toBeNull();
  });
});
