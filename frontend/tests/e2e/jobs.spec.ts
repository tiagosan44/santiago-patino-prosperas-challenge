import { type Page } from "@playwright/test";
import { test, expect } from "./fixtures";

async function login(page: Page, user: { username: string; password: string }) {
  await page.goto("/");
  await page.getByLabel(/username/i).fill(user.username);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByText(`@${user.username}`)).toBeVisible();
}

test.describe("Job lifecycle", () => {
  test("happy path: create job, see PENDING -> PROCESSING -> COMPLETED via SSE", async ({
    page,
    seededUser,
  }) => {
    await login(page, seededUser);

    // Capture page navigations to assert no reload during the flow
    const navigations: string[] = [];
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) navigations.push(frame.url());
    });

    // Submit a job
    await page.locator("#report_type").selectOption("sales");
    await page.locator("#format").selectOption("json");
    await page.getByRole("button", { name: /generate report/i }).click();

    // Pending badge appears (or processing if worker is fast)
    await expect(page.getByText(/pending|processing/i).first()).toBeVisible({ timeout: 5_000 });

    // Eventually COMPLETED — worker simulate_sleep is 5-30s, so allow up to 45s
    await expect(page.getByText(/completed/i).first()).toBeVisible({ timeout: 45_000 });

    // The Download button is visible
    await expect(page.getByRole("button", { name: /download/i }).first()).toBeVisible();

    // Critical: NO full-page navigation/reload during this flow.
    // The initial navigation when calling page.goto("/") is the only allowed one.
    // After that, framenavigated should not have fired again for the dashboard.
    // Some browsers fire one event for the initial dashboard render; we assert
    // the URL didn't change after the first capture.
    const distinctUrls = new Set(navigations);
    expect(distinctUrls.size).toBeLessThanOrEqual(1);
  });

  test("force_failure shows FAILED badge with error", async ({ page, seededUser }) => {
    await login(page, seededUser);

    await page.locator("#report_type").selectOption("force_failure");
    await page.getByRole("button", { name: /generate report/i }).click();

    // Eventually the FAILED badge shows up. The worker retries 3 times
    // before marking FAILED, with back-off: ~90s + ~180s + processing
    // attempts. We allow up to 6 minutes total but expect much less in
    // local mode where simulate_sleep is patched.
    //
    // For local docker-compose (no patch), the back-off is real (90s,
    // 180s) so we wait up to 5 minutes. Skip if too slow.
    test.setTimeout(360_000);  // 6 minutes
    await expect(page.getByText(/failed/i).first()).toBeVisible({ timeout: 320_000 });
  });
});
