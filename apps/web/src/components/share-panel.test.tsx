// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { InviteSummary } from "@/app/collections-actions";

const actions = vi.hoisted(() => ({
  inviteToCollection: vi.fn(),
  revokeInvite: vi.fn(),
}));
vi.mock("@/app/collections-actions", () => actions);

import { SharePanel } from "./share-panel";

const invite = (overrides: Partial<InviteSummary> = {}): InviteSummary => ({
  id: "i1",
  email: "sam@example.com",
  role: "viewer",
  expires_at: "2026-12-06T10:00:00Z",
  ...overrides,
});

beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("Inviting people", () => {
  it("invites an address with a Role and offers its link to copy", async () => {
    actions.inviteToCollection.mockResolvedValue({
      ok: true,
      value: invite({ id: "i9", email: "ana@example.com", role: "editor" }),
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<SharePanel collectionId="c2" initialInvites={[]} />);

    await userEvent.type(screen.getByLabelText("Email address"), "ana@example.com");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "editor");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));

    expect(actions.inviteToCollection).toHaveBeenCalledWith("c2", "ana@example.com", "editor");
    const link = screen.getByRole("textbox", { name: "Invite link for ana@example.com" });
    expect((link as HTMLInputElement).value).toBe(`${window.location.origin}/invites/i9`);
    expect(screen.getByText(/Send this link to ana@example.com. It works until 6 December 2026/)).toBeTruthy();
    await userEvent.click(screen.getAllByRole("button", { name: /^Copy link/ })[0]);
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/invites/i9`);
    expect(screen.getByRole("status").textContent).toContain("copied");
  });

  it("says why an invite was refused", async () => {
    actions.inviteToCollection.mockResolvedValue({
      ok: false,
      message: "sam@example.com already has access to this collection.",
    });
    render(<SharePanel collectionId="c2" initialInvites={[]} />);

    await userEvent.type(screen.getByLabelText("Email address"), "sam@example.com{Enter}");

    expect((await screen.findByRole("alert")).textContent).toContain("already has access");
    expect(screen.getByLabelText("Email address").getAttribute("aria-invalid")).toBe("true");
  });

  it("lists waiting invites, each cancellable", async () => {
    actions.revokeInvite.mockResolvedValue({ ok: true, value: null });
    render(<SharePanel collectionId="c2" initialInvites={[invite()]} />);

    const waiting = screen.getByRole("list");
    expect(within(waiting).getByText("sam@example.com")).toBeTruthy();
    expect(within(waiting).getByText(/Viewer · link works until 6 December 2026/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Cancel invite for sam@example.com" }));

    expect(actions.revokeInvite).toHaveBeenCalledWith("i1");
    expect(screen.queryByText("sam@example.com")).toBeNull();
    expect(document.activeElement).toBe(screen.getByLabelText("Email address"));
  });

  it("has no accessibility problems", async () => {
    const { container } = render(<SharePanel collectionId="c2" initialInvites={[invite()]} />);

    expect((await axe(container)).violations).toEqual([]);
  });
});
