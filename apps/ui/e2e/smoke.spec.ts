import { test, expect } from "@playwright/test";

test.describe("UI smoke", () => {
  test("login page renders heading and form controls", async ({ page }) => {
    await page.goto("/login");
    await expect(
      page.getByRole("heading", { name: /sign in to your account/i }),
    ).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByLabel(/username/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible({
      timeout: 15_000,
    });
  });
});
