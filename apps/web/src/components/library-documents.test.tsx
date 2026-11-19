// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { DocumentSummary } from "@/app/documents-actions";

const actions = vi.hoisted(() => ({
  deleteDocument: vi.fn(),
  finishUpload: vi.fn(),
  listDocuments: vi.fn(),
  retryDocument: vi.fn(),
  setEffectiveDate: vi.fn(),
  startUpload: vi.fn(),
}));
vi.mock("@/app/documents-actions", () => actions);
vi.mock("@/lib/supabase/client", () => ({ createClient: vi.fn() }));

import { LibraryDocuments } from "./library-documents";

const PERSONAL = { id: "c1", name: "Personal", role: "owner" as const, is_demo: false };

function aDocument(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    id: "d1",
    collection_id: "c1",
    name: "policy.pdf",
    size_bytes: 2048,
    status: "indexed",
    failure_reason: null,
    can_retry: false,
    source_url: null,
    source_credit: null,
    source_licence_url: null,
    replacement: null,
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

describe("Many Documents at once", () => {
  function mockStorage() {
    return import("@/lib/supabase/client").then(({ createClient }) =>
      vi.mocked(createClient).mockReturnValue({
        storage: {
          from: () => ({ uploadToSignedUrl: vi.fn().mockResolvedValue({ error: null }) }),
        },
      } as never),
    );
  }

  function acceptUploads() {
    let n = 0;
    actions.startUpload.mockImplementation(async (_c: string, name: string) => {
      n += 1;
      return {
        ok: true,
        value: {
          document: aDocument({ id: `u${n}`, name, status: "uploading" }),
          upload: { bucket: "documents", path: `c1/u${n}`, token: "t" },
        },
      };
    });
    actions.finishUpload.mockImplementation(async (id: string) => ({
      ok: true,
      value: aDocument({ id, name: id, status: "queued" }),
    }));
    actions.listDocuments.mockResolvedValue({ ok: true, value: [] });
  }

  it("shows how many are still being indexed, and hides it when all are done", () => {
    render(
      <LibraryDocuments
        collection={PERSONAL}
        initialDocuments={[
          aDocument({ id: "a", status: "embedding" }),
          aDocument({ id: "b", status: "queued", name: "b.md" }),
          aDocument({ id: "c", name: "c.md" }),
          // Left "uploading" by a closed tab: not work in progress here, and deletable.
          aDocument({ id: "d", status: "uploading", name: "abandoned.md" }),
        ]}
      />,
    );

    expect(screen.getByText("2 documents indexing…")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete abandoned.md" })).toBeTruthy();

    cleanup();
    render(<LibraryDocuments collection={PERSONAL} initialDocuments={[aDocument()]} />);
    expect(screen.queryByText(/indexing…/)).toBeNull();
  });

  it("uploads every file chosen at once, each as its own Document", async () => {
    await mockStorage();
    acceptUploads();
    const user = userEvent.setup();
    const { container } = render(<LibraryDocuments collection={PERSONAL} initialDocuments={[]} />);
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("no file input");

    const files = Array.from({ length: 7 }, (_, i) => new File([`text ${i}`], `note-${i}.md`));
    await user.upload(input, files);

    await waitFor(() => expect(actions.finishUpload).toHaveBeenCalledTimes(7));
    expect(new Set(actions.startUpload.mock.calls.map((call) => call[1]))).toEqual(
      new Set(files.map((f) => f.name)),
    );
    expect(await screen.findByRole("list", { name: "Documents" })).toBeTruthy();
  });

  function files(...names: string[]) {
    const list = names.map((name) => new File([name], name));
    return { files: list, types: ["Files"], dropEffect: "none" };
  }

  it("uploads files dropped anywhere on the page, and keeps the page", async () => {
    await mockStorage();
    acceptUploads();
    render(<LibraryDocuments collection={PERSONAL} initialDocuments={[aDocument()]} />);
    const dataTransfer = files("a.md", "b.txt");

    fireEvent.dragEnter(window, { dataTransfer });
    expect(screen.getByText(/Drop files to add them/)).toBeTruthy();
    const over = new Event("dragover", { cancelable: true });
    Object.assign(over, { dataTransfer });
    window.dispatchEvent(over);
    expect(over.defaultPrevented).toBe(true); // the browser won't open the file instead
    fireEvent.drop(window, { dataTransfer });

    await waitFor(() => expect(actions.finishUpload).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(/Drop files to add them/)).toBeNull();
  });

  it("keeps an earlier batch's messages when another batch starts", async () => {
    await mockStorage();
    acceptUploads();
    let release: () => void = () => undefined;
    actions.finishUpload.mockImplementationOnce(
      (id: string) =>
        new Promise((resolve) => {
          release = () => resolve({ ok: true, value: aDocument({ id, status: "queued" }) });
        }),
    );
    render(<LibraryDocuments collection={PERSONAL} initialDocuments={[aDocument()]} />);

    fireEvent.drop(window, { dataTransfer: files("slow.md", "slides.pptx") });
    expect((await screen.findByRole("alert")).textContent).toContain("slides.pptx can’t be added");
    fireEvent.drop(window, { dataTransfer: files("next.md") });

    await waitFor(() => expect(actions.startUpload).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("alert").textContent).toContain("slides.pptx can’t be added");
    release();
  });

  it("doesn't take drops from Viewers", () => {
    render(
      <LibraryDocuments
        collection={{ ...PERSONAL, role: "viewer" }}
        initialDocuments={[aDocument()]}
      />,
    );

    fireEvent.dragEnter(window, { dataTransfer: files("a.md") });

    expect(screen.queryByText(/Drop files to add them/)).toBeNull();
  });
});

describe("The Effective Date", () => {
  it("is shown, and Owners change it", async () => {
    actions.setEffectiveDate.mockResolvedValue({
      ok: true,
      value: aDocument({ effective_date: "2024-01-01" }),
    });
    render(<LibraryDocuments collection={PERSONAL} initialDocuments={[aDocument()]} />);

    expect(screen.getByText(/Effective 17 November 2026/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Change the effective date of policy.pdf" }));
    const input = screen.getByLabelText("Effective from");
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: "2024-01-01" } });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(actions.setEffectiveDate).toHaveBeenCalledWith("d1", "2024-01-01");
    expect(await screen.findByText(/Effective 1 January 2024/)).toBeTruthy();
  });

  it("keeps the form open with the reason when saving fails, and Escape cancels", async () => {
    actions.setEffectiveDate.mockResolvedValue({ ok: false, message: "You can’t change this." });
    render(<LibraryDocuments collection={PERSONAL} initialDocuments={[aDocument()]} />);

    await userEvent.click(screen.getByRole("button", { name: /Change the effective date/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("You can’t change this.");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByLabelText("Effective from")).toBeNull();
    // Opened again, it starts without the old message.
    await userEvent.click(screen.getByRole("button", { name: /Change the effective date/ }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("can't be changed by Viewers", () => {
    render(
      <LibraryDocuments
        collection={{ ...PERSONAL, role: "viewer" }}
        initialDocuments={[aDocument()]}
      />,
    );

    expect(screen.getByText(/Effective 17 November 2026/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Change the effective date/ })).toBeNull();
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

  it("waits while this page is still sending the Document's file", async () => {
    const { createClient } = await import("@/lib/supabase/client");
    vi.mocked(createClient).mockReturnValue({
      storage: { from: () => ({ uploadToSignedUrl: () => new Promise(() => undefined) }) },
    } as never);
    actions.startUpload.mockResolvedValue({
      ok: true,
      value: {
        document: aDocument({ id: "s1", name: "sending.md", status: "uploading" }),
        upload: { bucket: "documents", path: "c1/s1.md", token: "t" },
      },
    });
    render(<LibraryDocuments collection={PERSONAL} initialDocuments={[aDocument()]} />);

    fireEvent.drop(window, {
      dataTransfer: { files: [new File(["x"], "sending.md")], types: ["Files"] },
    });

    expect(await screen.findByText("sending.md")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete sending.md" })).toBeNull();
    expect(screen.getByText("1 document indexing…")).toBeTruthy();
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

describe("the Demo Collection", () => {
  const DEMO = { id: "demo", name: "Demo Collection", role: "viewer" as const, is_demo: true };

  it("shows only its own documents, each credited with a link to its source", () => {
    render(
      <LibraryDocuments
        collection={DEMO}
        initialDocuments={[
          aDocument(),
          aDocument({
            id: "d2",
            collection_id: "demo",
            name: "govuk-statutory-sick-pay.md",
            source_url: "https://www.gov.uk/statutory-sick-pay",
            source_credit: "GOV.UK, © Crown copyright. Licence: Open Government Licence v3.0.",
            source_licence_url: "https://www.nationalarchives.gov.uk/doc/open-government-licence/",
          }),
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "Demo Collection" })).toBeTruthy();
    expect(screen.queryByText("policy.pdf")).toBeNull();
    const credit = screen.getByRole("link", { name: /Crown copyright.*opens in a new tab/ });
    expect(credit.getAttribute("href")).toBe("https://www.gov.uk/statutory-sick-pay");
    const licence = screen.getByRole("link", { name: /^Licence/ });
    expect(licence.getAttribute("href")).toContain("open-government-licence");
    expect(screen.queryByRole("button", { name: /upload/i })).toBeNull();
  });

  it("says so when it has no documents yet", () => {
    render(<LibraryDocuments collection={DEMO} initialDocuments={[]} />);

    expect(screen.getByText(/no documents here yet/)).toBeTruthy();
  });
});

describe("Replacing a Document", () => {
  async function mockStorage() {
    const { createClient } = await import("@/lib/supabase/client");
    vi.mocked(createClient).mockReturnValue({
      storage: { from: () => ({ uploadToSignedUrl: vi.fn().mockResolvedValue({ error: null }) }) },
    } as never);
  }

  beforeEach(() => {
    actions.startUpload.mockResolvedValue({
      ok: true,
      value: {
        document: aDocument({ id: "v1", name: "policy-2025.pdf", status: "uploading" }),
        upload: { bucket: "documents", path: "c1/v1.pdf", token: "t" },
      },
    });
    actions.finishUpload.mockResolvedValue({
      ok: true,
      value: aDocument({ id: "v1", name: "policy-2025.pdf", status: "queued" }),
    });
    actions.listDocuments.mockResolvedValue({ ok: true, value: [aDocument()] });
  });

  it("sends the new file as a new version, and the Document keeps answering meanwhile", async () => {
    await mockStorage();
    const { container } = render(
      <LibraryDocuments collection={PERSONAL} initialDocuments={[aDocument()]} />,
    );
    const inputs = container.querySelectorAll<HTMLInputElement>('input[type="file"]');
    const rowInput = inputs[inputs.length - 1];

    await userEvent.upload(rowInput, new File(["new"], "policy-2025.pdf"));

    await waitFor(() => expect(actions.finishUpload).toHaveBeenCalledWith("v1"));
    expect(actions.startUpload.mock.calls[0][5]).toBe("d1"); // replaces policy.pdf
    expect(await screen.findByText(/Replacing with policy-2025.pdf: waiting to be processed/)).toBeTruthy();
    expect(screen.getAllByRole("listitem", { name: "policy.pdf" })).toHaveLength(1); // one row
    // One replacement at a time: Replace returns once this one is done or dismissed.
    expect(screen.queryByRole("button", { name: "Replace policy.pdf" })).toBeNull();
  });

  it("offers Replace when a file with the same name is uploaded", async () => {
    await mockStorage();
    const { container } = render(
      <LibraryDocuments collection={PERSONAL} initialDocuments={[aDocument()]} />,
    );
    const picker = container.querySelector<HTMLInputElement>('input[type="file"][multiple]');
    if (!picker) throw new Error("no picker");

    await userEvent.upload(picker, new File(["new"], "policy.pdf"));

    const prompt = await screen.findByRole("list", { name: "Already in this collection" });
    expect(prompt.textContent).toContain("policy.pdf is already in this collection. Replace it");
    expect(actions.startUpload).not.toHaveBeenCalled();
    await userEvent.click(within(prompt).getByRole("button", { name: "Replace with this file" }));
    await waitFor(() => expect(actions.startUpload).toHaveBeenCalled());
    expect(actions.startUpload.mock.calls[0][5]).toBe("d1");
  });

  it("shows why a replacement failed, and Dismiss leaves the current version", async () => {
    actions.deleteDocument.mockResolvedValue({ ok: true, value: null });
    render(
      <LibraryDocuments
        collection={PERSONAL}
        initialDocuments={[
          aDocument({
            replacement: {
              id: "v1",
              name: "policy-2025.pdf",
              status: "failed",
              failure_reason: "This PDF is scanned.",
              can_retry: false,
            },
          }),
        ]}
      />,
    );

    expect(screen.getByText(/policy-2025.pdf couldn’t replace policy.pdf: This PDF is scanned./)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss the failed replacement of policy.pdf" }));

    expect(actions.deleteDocument).toHaveBeenCalledWith("v1");
    await waitFor(() => expect(screen.queryByText(/couldn’t replace/)).toBeNull());
  });
});
