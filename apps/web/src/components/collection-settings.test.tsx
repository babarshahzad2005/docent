// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

const actions = vi.hoisted(() => ({
  createCollection: vi.fn(),
  deleteCollection: vi.fn(),
  renameCollection: vi.fn(),
}));
const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("@/app/collections-actions", () => actions);
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { CollectionSettings, NewCollection } from "./collection-settings";

const TEAM = { id: "c2", name: "Team handbook" };
const created = (name: string) => ({
  ok: true,
  value: { id: "c9", name, is_personal: false, is_demo: false, role: "owner" },
});

beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("New collection", () => {
  it("asks for a name, creates it, and opens it", async () => {
    actions.createCollection.mockResolvedValue(created("HR policies"));
    render(<NewCollection />);

    await userEvent.click(screen.getByRole("button", { name: "New collection" }));
    const name = screen.getByLabelText("Collection name");
    expect(document.activeElement).toBe(name);
    await userEvent.type(name, "HR policies{Enter}");

    expect(actions.createCollection).toHaveBeenCalledWith("HR policies");
    expect(router.push).toHaveBeenCalledWith("/collections/c9");
  });

  it("says why a name was refused, and Escape puts the button back", async () => {
    actions.createCollection.mockResolvedValue({
      ok: false,
      message: "Keep the name to 120 characters or fewer.",
    });
    render(<NewCollection />);

    await userEvent.click(screen.getByRole("button", { name: "New collection" }));
    await userEvent.type(screen.getByLabelText("Collection name"), "Too long{Enter}");
    expect((await screen.findByRole("alert")).textContent).toContain("120 characters");
    expect(router.push).not.toHaveBeenCalled();

    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "New collection" })).toBeTruthy();
  });

  it("has no accessibility problems while open", async () => {
    const { container } = render(<NewCollection />);
    await userEvent.click(screen.getByRole("button", { name: "New collection" }));

    expect((await axe(container)).violations).toEqual([]);
  });
});

describe("Collection settings", () => {
  it("renames the collection", async () => {
    actions.renameCollection.mockResolvedValue(created("Handbook"));
    render(<CollectionSettings collection={TEAM} documentCount={0} invites={[]} />);

    await userEvent.click(screen.getByRole("button", { name: "Rename Team handbook" }));
    const name = screen.getByLabelText("New name");
    await userEvent.clear(name);
    await userEvent.type(name, "Handbook{Enter}");

    expect(actions.renameCollection).toHaveBeenCalledWith("c2", "Handbook");
    expect(router.refresh).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Rename Team handbook" })).toBeTruthy();
  });

  it("deletes it after a confirmation that says how many documents go with it", async () => {
    actions.deleteCollection.mockResolvedValue({ ok: true, value: null });
    render(<CollectionSettings collection={TEAM} documentCount={3} invites={[]} />);

    await userEvent.click(screen.getByRole("button", { name: "Delete collection" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("Its 3 documents");
    expect(dialog.textContent).toContain("can’t be undone");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete collection" }));

    expect(actions.deleteCollection).toHaveBeenCalledWith("c2");
    expect(router.push).toHaveBeenCalledWith("/");
  });

  it("keeps the dialog open and says why when deleting fails", async () => {
    actions.deleteCollection.mockResolvedValue({
      ok: false,
      message: "Only the collection’s owner can do that.",
    });
    render(<CollectionSettings collection={TEAM} documentCount={1} invites={[]} />);

    await userEvent.click(screen.getByRole("button", { name: "Delete collection" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete collection" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Only the collection’s owner");
    expect(router.push).not.toHaveBeenCalled();
  });
});
