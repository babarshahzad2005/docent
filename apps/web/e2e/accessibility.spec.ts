import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function expectNoViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  expect(
    violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`),
  ).toEqual([]);
}

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} mode`, () => {
    test.use({ colorScheme });

    test("the sign-in page meets WCAG 2.2 AA", async ({ page }) => {
      await page.goto("/sign-in");
      await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();

      await expectNoViolations(page);
    });

    test("a sign-in link error is announced and still meets WCAG 2.2 AA", async ({ page }) => {
      await page.goto("/sign-in?error=link");
      // Next.js adds its own route announcer with role="alert", so pick ours by its text.
      await expect(page.getByRole("alert").filter({ hasText: "didn't work" })).toBeVisible();

      await expectNoViolations(page);
    });

    test("the privacy notice meets WCAG 2.2 AA", async ({ page }) => {
      await page.goto("/privacy");
      await expect(page.getByRole("heading", { level: 1, name: "Privacy notice" })).toBeVisible();

      await expectNoViolations(page);
    });
  });
}

test("signed-out visitors are sent to sign-in, and come back to where they were going", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/sign-in$/);

  await page.goto("/collections/example");
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fcollections%2Fexample$/);
});

test("the sign-in page has one h1, a labelled email field, and both sign-in options", async ({
  page,
}) => {
  await page.goto("/sign-in");

  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(page.getByLabel("Email")).toHaveAttribute("type", "email");
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Email me a sign-in link" })).toBeVisible();
});
