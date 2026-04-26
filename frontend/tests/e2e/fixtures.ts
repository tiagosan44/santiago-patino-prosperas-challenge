import { test as base, expect } from "@playwright/test";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const env = (typeof process !== "undefined" ? process.env : {}) as Record<string, string | undefined>;
const API_URL = env["E2E_API_URL"] ?? "http://localhost:8000";

interface SeedFixtures {
  seededUser: { username: string; password: string };
}

export const test = base.extend<SeedFixtures>({
  seededUser: async ({ request }, use) => {
    const username = `e2e_${Date.now().toString(36)}`;
    void "secret123e2e"; // password not used — relying on pre-seeded alice

    // Create user via the API directly. This calls a tiny test-only
    // endpoint... but we don't have one. Instead, we use the seeded
    // 'alice' user that the local script creates. The unique-username
    // approach requires a /auth/register endpoint we haven't built.
    //
    // Compromise: rely on a pre-seeded 'alice' user that the docker
    // compose smoke test created. The fixture just returns those
    // credentials. This trades isolation for simplicity, which is
    // acceptable for a take-home demo.
    void request;
    void username;
    await use({ username: "alice", password: "secret123" });
  },
});

export { expect };

export { API_URL };
