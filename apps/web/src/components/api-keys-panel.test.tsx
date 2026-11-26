// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { ApiKeySummary } from "@/app/collections-actions";

const actions = vi.hoisted(() => ({ createApiKey: vi.fn(), revokeApiKey: vi.fn() }));
vi.mock("@/app/collections-actions", () => actions);

import { ApiKeysPanel } from "./api-keys-panel";

const key = (overrides: Partial<ApiKeySummary> = {}): ApiKeySummary => ({
  id: "k1",
  name: "Help centre",
  created_at: "2026-11-20T10:00:00Z",
  last_used_at: null,
  ...overrides,
});

beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("API keys", () => {
  it("shows a new key's secret once, to copy", async () => {
    actions.createApiKey.mockResolvedValue({
      ok: true,
      value: { key: key({ id: "k9", name: "Script" }), secret: "dk_secret" },
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { container } = render(<ApiKeysPanel collectionId="c1" initialKeys={[]} />);

    await userEvent.type(screen.getByLabelText("Key name"), "Script{Enter}");

    expect(actions.createApiKey).toHaveBeenCalledWith("c1", "Script");
    const secret = screen.getByRole("textbox", { name: "API key for Script" });
    expect((secret as HTMLInputElement).value).toBe("dk_secret");
    expect(document.activeElement).toBe(secret);
    expect(screen.getByText(/can’t be shown\s+again/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Copy key" }));
    expect(writeText).toHaveBeenCalledWith("dk_secret");
    expect((await axe(container)).violations).toEqual([]);

    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("textbox", { name: "API key for Script" })).toBeNull();
    expect(container.textContent).not.toContain("dk_secret");
  });

  it("lists keys by name, creation and last use, never their secrets", () => {
    render(
      <ApiKeysPanel
        collectionId="c1"
        initialKeys={[key(), key({ id: "k2", name: "Bot", last_used_at: "2026-11-25T09:00:00Z" })]}
      />,
    );

    expect(screen.getByText("Created 20 November 2026 · never used")).toBeTruthy();
    expect(screen.getByText("Created 20 November 2026 · last used 25 November 2026")).toBeTruthy();
  });

  it("revokes a key after asking", async () => {
    actions.revokeApiKey.mockResolvedValue({ ok: true, value: null });
    render(<ApiKeysPanel collectionId="c1" initialKeys={[key()]} />);

    await userEvent.click(screen.getByRole("button", { name: "Revoke Help centre" }));
    expect(screen.getByText(/stops getting answers at once/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Revoke key" }));

    expect(actions.revokeApiKey).toHaveBeenCalledWith("k1");
    expect(screen.queryByText("Help centre")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("revoked");
  });

  it("says why a key wasn't created", async () => {
    actions.createApiKey.mockResolvedValue({ ok: false, message: "Keep the name short." });
    render(<ApiKeysPanel collectionId="c1" initialKeys={[]} />);

    await userEvent.type(screen.getByLabelText("Key name"), "x{Enter}");

    expect((await screen.findByRole("alert")).textContent).toBe("Keep the name short.");
  });
});
