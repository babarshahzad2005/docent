// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { DocumentSummary } from "@/app/documents-actions";

const actions = vi.hoisted(() => ({
  deleteDocument: vi.fn(),
  finishUpload: vi.fn(),
  listDocuments: vi.fn(),
  retryDocument: vi.fn(),
  startUpload: vi.fn(),
}));
vi.mock("@/app/documents-actions", () => actions);
vi.mock("@/lib/supabase/client", () => ({ createClient: vi.fn() }));

import { LibraryDocuments } from "./library-documents";

const PERSONAL = { id: "c1", name: "Personal", role: "owner" as const };

function aDocument(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    id: "d1",
    collection_id: "c1",
    name: "policy.pdf",
    size_bytes: 2048,
    status: "indexed",
    failure_reason: null,
    can_retry: false,
    effective_date: "2026-11-17",
    created_at: "2026-11-17T10:00:00Z",
    updated_at: "2026-11-17T10:00:00Z",
    ...overrides,
  };
}

beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("Deleting a Document", () => {
  it("asks first, naming the Document, and removes it once confirmed", async () => {
    actions.deleteDocument.mockResolvedValue({ ok: true, value: null });
    const user = userEvent.setup();
    render(
      <LibraryDocuments
        collection={PERSONAL}
        initialDocuments={[aDocument(), aDocument({ id: "d2", name: "notes.md" })]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Delete policy.pdf" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete policy.pdf?" });
    const results = await axe(dialog, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(actions.deleteDocument).toHaveBeenCalledWith("d1");
    expect(screen.queryByText("policy.pdf")).toBeNull();
    expect(screen.getByText("notes.md")).toBeTruthy();
    expect(screen.getByText("policy.pdf was deleted.")).toBeTruthy();
    expect(document.activeElement?.textContent).toContain("Upload documents");
  });

  it("changes nothing when cancelled", async () => {
    const user = userEvent.setup();
    render(<LibraryDocuments collection={PERSONAL} initialDocuments={[aDocument()]} />);

    await user.click(screen.getByRole("button", { name: "Delete policy.pdf" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(actions.deleteDocument).not.toHaveBeenCalled();
    expect(screen.getByText("policy.pdf")).toBeTruthy();
  });

  it("keeps the dialog open and says why when deleting fails", async () => {
    actions.deleteDocument.mockResolvedValue({ ok: false, message: "Storage isn't answering." });
    const user = userEvent.setup();
    render(<LibraryDocuments collection={PERSONAL} initialDocuments={[aDocument()]} />);

    await user.click(screen.getByRole("button", { name: "Delete policy.pdf" }));
    await user.click(await screen.findByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "Storage isn't answering.",
    );
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(screen.getByText("policy.pdf", { selector: "span" })).toBeTruthy();
  });

  it("isn't offered to Viewers", () => {
    render(
      <LibraryDocuments
        collection={{ ...PERSONAL, role: "viewer" }}
        initialDocuments={[aDocument()]}
      />,
    );

    expect(screen.queryByRole("button", { name: "Delete policy.pdf" })).toBeNull();
  });
});
