import { test, expect } from "./fixtures";

test.describe("Authentication", () => {
  test("invalid credentials show inline error", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /prosperas reports/i })).toBeVisible();

    await page.getByLabel(/username/i).fill("alice");
    await page.getByLabel(/password/i).fill("wrongpassword");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page.getByRole("alert")).toContainText(/invalid credentials/i);
    // Still on login page — no token, no dashboard
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
  });

  test("valid credentials lead to dashboard", async ({ page, seededUser }) => {
    await page.goto("/");
    await page.getByLabel(/username/i).fill(seededUser.username);
    await page.getByLabel(/password/i).fill(seededUser.password);
    await page.getByRole("button", { name: /sign in/i }).click();

    // Header with username + sign out
    await expect(page.getByText(`@${seededUser.username}`)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: /sign out/i })).toBeVisible();
  });

  test("sign out returns to login page", async ({ page, seededUser }) => {
    await page.goto("/");
    await page.getByLabel(/username/i).fill(seededUser.username);
    await page.getByLabel(/password/i).fill(seededUser.password);
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByText(`@${seededUser.username}`)).toBeVisible();

    await page.getByRole("button", { name: /sign out/i }).click();
    await expect(page.getByLabel(/username/i)).toBeVisible();
  });
});
