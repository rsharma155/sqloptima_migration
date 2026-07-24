import { test, expect, type Page } from "@playwright/test";

async function seedAuthCookie(page: Page) {
  await page.context().addCookies([
    {
      name: "auth_token",
      value: "e2e-test-token",
      url: "http://127.0.0.1:3508",
    },
  ]);
}

async function mockCoreApis(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/migrations") && route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
      return;
    }
    if (url.includes("/connections") && route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
      return;
    }
    if (url.includes("/sql/convert") || url.includes("/convert")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          converted_sql: "CREATE OR REPLACE PROCEDURE demo() LANGUAGE plpgsql AS $$ BEGIN NULL; END; $$;",
          warnings: [],
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    });
  });
}

test.describe("UI core flows", () => {
  test("unauthenticated migrations redirects to login", async ({ page }) => {
    await page.goto("/migrations");
    await expect(page).toHaveURL(/\/login/);
    await expect(
      page.getByRole("heading", { name: /sign in to your account/i }),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("migrations list page renders with auth cookie", async ({ page }) => {
    await seedAuthCookie(page);
    await mockCoreApis(page);
    await page.goto("/migrations");
    await expect(page).not.toHaveURL(/\/login/);
    // Wizard / list chrome — New migration or Migrations heading
    await expect(
      page.getByRole("heading", { name: /migration/i }).first(),
    ).toBeVisible({ timeout: 20_000 });
  });

  test("SQL converter page renders convert controls", async ({ page }) => {
    await seedAuthCookie(page);
    await mockCoreApis(page);
    await page.goto("/sql");
    await expect(page.getByRole("heading", { name: /sql converter/i })).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByRole("button", { name: /^convert$/i })).toBeVisible();
  });

  test("setup page is reachable without auth", async ({ page }) => {
    await page.goto("/setup");
    await expect(page).toHaveURL(/\/setup/);
    // Connection wizard / setup content should render something meaningful
    await expect(page.locator("body")).toContainText(/connection|setup|sql server|postgres/i, {
      timeout: 20_000,
    });
  });
});
