// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { MemberSummary } from "@/app/collections-actions";

const actions = vi.hoisted(() => ({
  changeRole: vi.fn(),
  removeMember: vi.fn(),
  transferOwnership: vi.fn(),
}));
const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("@/app/collections-actions", () => actions);
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { MembersList } from "./members-list";

const TEAM = { id: "c2", name: "Team handbook" };
const member = (overrides: Partial<MemberSummary>): MemberSummary => ({
  user_id: "u1",
  email: "owner@example.com",
  role: "owner",
  is_you: false,
  ...overrides,
});
const OWNER_VIEW = [
  member({ is_you: true }),
  member({ user_id: "u2", email: "ana@example.com", role: "editor" }),
  member({ user_id: "u3", email: "sam@example.com", role: "viewer" }),
];

beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("People with access, for the Owner", () => {
  it("changes a Member's Role", async () => {
    actions.changeRole.mockResolvedValue({ ok: true, value: null });
    render(<MembersList collection={TEAM} initialMembers={OWNER_VIEW} isOwner />);

    await userEvent.selectOptions(screen.getByLabelText("Role for sam@example.com"), "editor");

    expect(actions.changeRole).toHaveBeenCalledWith("c2", "u3", "editor");
    expect(screen.getByRole("status").textContent).toContain("sam@example.com is now an editor");
  });

  it("removes a Member after asking", async () => {
    actions.removeMember.mockResolvedValue({ ok: true, value: null });
    render(<MembersList collection={TEAM} initialMembers={OWNER_VIEW} isOwner />);

    await userEvent.click(screen.getByRole("button", { name: "Remove ana@example.com" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("from their next question");
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    expect(actions.removeMember).toHaveBeenCalledWith("c2", "u2");
    expect(screen.queryByText("ana@example.com")).toBeNull();
  });

  it("hands ownership over after asking", async () => {
    actions.transferOwnership.mockResolvedValue({ ok: true, value: null });
    render(<MembersList collection={TEAM} initialMembers={OWNER_VIEW} isOwner />);

    await userEvent.click(screen.getByRole("button", { name: "Make owner: sam@example.com" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("You’ll stay, as an editor");
    await userEvent.click(within(dialog).getByRole("button", { name: "Make owner" }));

    expect(actions.transferOwnership).toHaveBeenCalledWith("c2", "u3");
    expect(router.refresh).toHaveBeenCalled();
  });

  it("can't change the Owner's own Role, or let them leave", () => {
    render(<MembersList collection={TEAM} initialMembers={OWNER_VIEW} isOwner />);

    const owner = screen.getByText("owner@example.com").closest("li");
    expect(owner).not.toBeNull();
    expect(within(owner as HTMLElement).queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Leave collection" })).toBeNull();
  });

  it("has no accessibility problems", async () => {
    const { container } = render(
      <MembersList collection={TEAM} initialMembers={OWNER_VIEW} isOwner />,
    );

    expect((await axe(container)).violations).toEqual([]);
  });
});

describe("People with access, for everyone else", () => {
  const VIEWER_VIEW = [
    member({}),
    member({ user_id: "u3", email: "sam@example.com", role: "viewer", is_you: true }),
  ];

  it("shows Roles without controls, and lets them leave", async () => {
    actions.removeMember.mockResolvedValue({ ok: true, value: null });
    render(<MembersList collection={TEAM} initialMembers={VIEWER_VIEW} isOwner={false} />);

    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
    expect(screen.getByText("Owner")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Leave collection" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Leave" }));

    expect(actions.removeMember).toHaveBeenCalledWith("c2", "u3");
    expect(router.push).toHaveBeenCalledWith("/");
  });

  it("says why leaving failed, and stays", async () => {
    actions.removeMember.mockResolvedValue({ ok: false, message: "Can’t reach the server." });
    render(<MembersList collection={TEAM} initialMembers={VIEWER_VIEW} isOwner={false} />);

    await userEvent.click(screen.getByRole("button", { name: "Leave collection" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Leave" }));

    expect((await within(dialog).findByRole("alert")).textContent).toContain("Can’t reach");
    expect(router.push).not.toHaveBeenCalled();
  });
});
