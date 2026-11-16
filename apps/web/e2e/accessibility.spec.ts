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

    test("the empty Library meets WCAG 2.2 AA", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1, name: "Your library is empty" })).toBeVisible();
      // Wait for streamed content to settle before scanning.
      await expect(page.getByText("Checking the server…")).toHaveCount(0);

      await expectNoViolations(page);
    });
  });
}

test("the page has one h1 and the expected landmarks", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Upload documents" })).toBeVisible();
});

test("on tablets, the Library opens in a drawer that can be used by keyboard", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "tablet", "The drawer only exists below 1024px.");
  await page.goto("/");

  await expect(page.getByRole("navigation", { name: "Library" })).toBeHidden();

  const open = page.getByRole("button", { name: "Open library" });
  await open.focus();
  await page.keyboard.press("Enter");

  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("navigation", { name: "Library" })).toBeVisible();
  await expectNoViolations(page);

  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(open).toBeFocused();
});
