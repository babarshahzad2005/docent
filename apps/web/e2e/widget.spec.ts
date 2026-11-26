import { expect, test } from "@playwright/test";

const COLLECTION = "7b0e2f4a-1c3d-4e5f-8a9b-0c1d2e3f4a5b";
// Another origin (127.0.0.1, not localhost) that stays on this machine: Chrome won't let a
// public https page load scripts from localhost.
const HOST_PAGE = "http://127.0.0.1:3100/__host-page";

// A plain page on another origin whose styles try hard to change everything (#96).
test("the Widget loader works on another site, untouched by its styles", async ({
  page,
  baseURL,
}) => {
  await page.route(HOST_PAGE, (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><html><head><style>
        * { all: unset; color: red !important; font-size: 40px !important }
        button, div, iframe { display: none !important; background: red !important }
      </style></head><body><h1>Someone's site</h1>
      <script src="${baseURL}/widget.js" data-collection="${COLLECTION}" async></script>
      </body></html>`,
    }),
  );
  await page.goto(HOST_PAGE);

  const open = page.getByRole("button", { name: "Ask a question" });
  await expect(open).toBeVisible();
  await expect(open).toHaveAttribute("aria-expanded", "false");
  await expect(open).toHaveCSS("width", "56px");

  await open.click();
  const panel = page.getByRole("dialog", { name: "Ask Docent" });
  await expect(panel).toBeVisible();
  await expect(page.getByTitle("Docent chat")).toHaveAttribute(
    "src",
    `${baseURL}/embed/${COLLECTION}`,
  );
  await expect(open).toHaveAttribute("aria-expanded", "true");

  await panel.getByRole("button", { name: "Close chat" }).click();
  await expect(panel).toBeHidden();
  await expect(open).toBeFocused();
});

test("a phone sees the Widget full screen, with its own Close button", async ({
  page,
  baseURL,
}) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.route(HOST_PAGE, (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><body><script src="${baseURL}/widget.js" data-collection="${COLLECTION}"></script></body>`,
    }),
  );
  await page.goto(HOST_PAGE);

  await page.getByRole("button", { name: "Ask a question" }).click();
  const panel = page.getByRole("dialog", { name: "Ask Docent" });
  await expect(panel).toHaveCSS("width", "375px");
  await expect(panel).toHaveAttribute("aria-modal", "true");
  await panel.getByRole("button", { name: "Close chat" }).focus();
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
});
