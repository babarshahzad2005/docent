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

describe("Uploading", () => {
  function picker(container: HTMLElement): HTMLInputElement {
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("no file input");
    return input;
  }

  it("refuses files that break a rule before sending anything", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { container } = render(<LibraryDocuments collection={PERSONAL} initialDocuments={[]} />);

    await user.upload(picker(container), new File(["x"], "slides.pptx"));

    expect((await screen.findByRole("alert")).textContent).toContain("slides.pptx can’t be added");
    expect(actions.startUpload).not.toHaveBeenCalled();
  });

  it("lets the User keep both when the same file is already in the Collection", async () => {
    const upload = vi.fn().mockResolvedValue({ error: null });
    const { createClient } = await import("@/lib/supabase/client");
    vi.mocked(createClient).mockReturnValue({
      storage: { from: () => ({ uploadToSignedUrl: upload }) },
    } as never);
    actions.startUpload
      .mockResolvedValueOnce({
        ok: false,
        duplicate: true,
        message: "policy.md is already in your Personal collection as policy.md.",
      })
      .mockResolvedValueOnce({
        ok: true,
        value: {
          document: aDocument({ id: "d9", name: "policy.md", status: "uploading" }),
          upload: { bucket: "documents", path: "c1/d9.md", token: "t" },
        },
      });
    actions.finishUpload.mockResolvedValue({
      ok: true,
      value: aDocument({ id: "d9", name: "policy.md", status: "queued" }),
    });
    actions.listDocuments.mockResolvedValue({ ok: true, value: [] });
    const user = userEvent.setup();
    const { container } = render(<LibraryDocuments collection={PERSONAL} initialDocuments={[]} />);

    await user.upload(picker(container), new File(["# Leave"], "policy.md"));
    const question = await screen.findByRole("list", { name: "Already in this collection" });
    expect(question.textContent).toContain(
      "policy.md is already in your Personal collection as policy.md.",
    );
    const [, , , fingerprint, allowed] = actions.startUpload.mock.calls[0];
    expect(fingerprint).toMatch(/^[0-9a-f]{64}$/);
    expect(allowed).toBe(false);

    await user.click(screen.getByRole("button", { name: "Upload anyway" }));

    await waitFor(() => expect(actions.finishUpload).toHaveBeenCalledWith("d9"));
    expect(actions.startUpload.mock.calls[1][4]).toBe(true);
    expect(upload).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Upload anyway" })).toBeNull();
  });

  it("skips a duplicate when asked", async () => {
    actions.startUpload.mockResolvedValue({
      ok: false,
      duplicate: true,
      message: "policy.md is already in your Personal collection as policy.md.",
    });
    const user = userEvent.setup();
    const { container } = render(<LibraryDocuments collection={PERSONAL} initialDocuments={[]} />);

    await user.upload(picker(container), new File(["# Leave"], "policy.md"));
    await user.click(await screen.findByRole("button", { name: "Skip" }));

    expect(screen.queryByRole("list", { name: "Already in this collection" })).toBeNull();
    expect(actions.startUpload).toHaveBeenCalledOnce();
    expect(document.activeElement?.textContent).toContain("Upload documents");
  });

  it("cancels the half-made Document when the file can't be sent", async () => {
    const { createClient } = await import("@/lib/supabase/client");
    vi.mocked(createClient).mockReturnValue({
      storage: {
        from: () => ({
          uploadToSignedUrl: vi.fn().mockResolvedValue({ error: { message: "network down" } }),
        }),
      },
    } as never);
    actions.startUpload.mockResolvedValue({
      ok: true,
      value: {
        document: aDocument({ id: "d7", name: "policy.md", status: "uploading" }),
        upload: { bucket: "documents", path: "c1/d7.md", token: "t" },
      },
    });
    actions.deleteDocument.mockResolvedValue({ ok: true, value: null });
    const user = userEvent.setup();
    const { container } = render(<LibraryDocuments collection={PERSONAL} initialDocuments={[]} />);

    await user.upload(picker(container), new File(["# Leave"], "policy.md"));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "policy.md couldn't be uploaded (network down)",
    );
    expect(actions.deleteDocument).toHaveBeenCalledWith("d7");
    expect(actions.finishUpload).not.toHaveBeenCalled();
  });
});

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

  it("waits until a Document's upload has finished", () => {
    render(
      <LibraryDocuments
        collection={PERSONAL}
        initialDocuments={[aDocument({ status: "uploading" })]}
      />,
    );

    expect(screen.queryByRole("button", { name: "Delete policy.pdf" })).toBeNull();
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
