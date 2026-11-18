// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

const passages = vi.hoisted(() => ({ getPassage: vi.fn() }));
vi.mock("@/app/passages-actions", () => passages);

import { Conversation, type Turn } from "./conversation";

function screenWidth(wide: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: wide,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

function sse(...events: [string, object][]): Response {
  const body = events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}

const START = {
  conversation_id: "c1",
  message_id: "m1",
  sources: [
    { number: 1, document_id: "d1", document_name: "leave.pdf", heading_path: ["Leave"], page: 9 },
  ],
};

describe("Conversation", () => {
  beforeEach(() => screenWidth(true));

  it("streams an answer, names its sources, and announces it once complete", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sse(
          ["start", START],
          ["delta", { text: "Up to 10 days " }],
          ["delta", { text: "carry over 【1】." }],
          [
            "done",
            {
              message_id: "m1",
              outcome: "answered",
              cited: [1],
              answer: "Up to 10 days carry over [1].",
              verified: true,
              removed: [],
            },
          ],
        ),
      ),
    );
    const { container } = render(
      <Conversation conversationId={null} initialTurns={[]} startQuestion="How much carries over?" />,
    );

    const citation = await screen.findByRole("button", { name: "Source 1, leave.pdf, page 9" });
    expect(citation.textContent).toBe("1");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("How much carries over?");
    expect(screen.getByRole("list", { name: "Sources" }).textContent).toContain("Page 9");
    await waitFor(() =>
      expect(screen.getByText("Up to 10 days carry over .", { selector: "p" })).toBeTruthy(),
    );
    expect(screen.getByText("The citation was checked against its source.")).toBeTruthy();
    expect(window.location.pathname).toBe("/conversations/c1");
    const results = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });

  it("fades out an unsupported claim, then shows what was removed and why", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sse(
          ["start", START],
          ["delta", { text: "Up to 10 days carry over [1]. Unused days are paid out [1]." }],
          [
            "done",
            {
              message_id: "m1",
              outcome: "answered",
              cited: [1],
              answer: "Up to 10 days carry over [1].",
              verified: true,
              removed: [
                {
                  text: "Unused days are paid out.",
                  reason: "the cited passage doesn’t say this",
                  original: "Unused days are paid out [1].",
                },
              ],
            },
          ],
        ),
      ),
    );
    render(<Conversation conversationId={null} initialTurns={[]} startQuestion="How much?" />);

    await screen.findByText("What was removed");
    expect(screen.queryByText(/paid out \[|paid out $/)).toBeNull();
    expect(document.querySelector("[data-fading]")).toBeNull();
    expect(
      screen.getByText(
        "1 citation was checked against its source. 1 claim was removed because it couldn’t be checked.",
      ),
    ).toBeTruthy();
    await userEvent.click(screen.getByText("What was removed"));
    expect(screen.getByText("“Unused days are paid out.”")).toBeTruthy();
  });

  it("marks an answer cut off without an ending, and lets the User ask again", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(sse(["start", START], ["delta", { text: "Up to 10" }])),
    );
    render(<Conversation conversationId="c1" initialTurns={[]} startQuestion="How much?" />);

    expect((await screen.findByRole("alert")).textContent).toContain("The answer was cut off");
    expect(screen.getByRole("button", { name: "Ask again" })).toHaveProperty("disabled", false);
    expect(screen.getByRole("textbox", { name: "Ask a follow-up question" })).toBeTruthy();
  });

  it("explains a refused question", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ detail: "That conversation doesn’t exist." }, { status: 404 })),
    );
    render(<Conversation conversationId="gone" initialTurns={[]} startQuestion="Hello?" />);

    expect((await screen.findByRole("alert")).textContent).toContain("doesn’t exist");
  });
});

const SAVED: Turn = {
  question: "How much leave carries over?",
  answer: "Up to 10 days [1].",
  status: "complete",
  messageId: "m1",
  cited: [1],
  sources: [
    {
      number: 1,
      chunk_id: "k1",
      document_id: "d1",
      document_name: "leave.pdf",
      heading_path: ["Leave", "Carry-over"],
      page: 9,
      passage: "Unused leave of up to 10 days carries over.",
    },
  ],
};

describe("The source of a Citation", () => {
  it("opens beside the answer on wide screens, highlighted in context, and closes with Escape", async () => {
    screenWidth(true);
    passages.getPassage.mockResolvedValue({
      ok: true,
      value: {
        chunk_id: "k1",
        document_id: "d1",
        document_name: "leave.pdf",
        heading_path: ["Leave", "Carry-over"],
        page: 9,
        content: "Unused leave of up to 10 days carries over.",
        before: "Leave accrues monthly.",
        after: "The rest is forfeited.",
      },
    });
    const user = userEvent.setup();
    const { container } = render(
      <Conversation conversationId="c1" initialTurns={[SAVED]} />,
    );
    const citation = screen.getByRole("button", { name: "Source 1, leave.pdf, page 9" });

    await user.click(citation);

    const pane = screen.getByRole("complementary", { name: "Source" });
    expect(screen.getByRole("heading", { level: 2, name: "leave.pdf" })).toBe(document.activeElement);
    expect(pane.querySelector("mark")?.textContent).toBe("Unused leave of up to 10 days carries over.");
    expect(await screen.findByText("Leave accrues monthly.")).toBeTruthy();
    expect(screen.getByText("The rest is forfeited.")).toBeTruthy();
    expect(pane.textContent).toContain("Page 9");
    expect(passages.getPassage).toHaveBeenCalledWith("k1");
    const results = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);

    await waitFor(() => expect(pane.querySelector("mark[data-shown]")).toBeTruthy());

    // Escape closes it from anywhere on the page, not only from inside the pane.
    screen.getByRole("textbox", { name: "Ask a follow-up question" }).focus();
    await user.keyboard("{Escape}");

    expect(document.activeElement).toBe(citation);
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Source" })).toBeNull());
  });

  it("opens from the Sources list too, and says when the Document was removed", async () => {
    screenWidth(true);
    const removed: Turn = {
      ...SAVED,
      sources: [{ ...SAVED.sources[0], chunk_id: null, document_id: null }],
    };
    const user = userEvent.setup();
    render(<Conversation conversationId="c1" initialTurns={[removed]} />);

    await user.click(screen.getByRole("list", { name: "Sources" }).querySelector("button")!);

    const pane = screen.getByRole("complementary", { name: "Source" });
    expect(pane.textContent).toContain("This document has been removed");
    expect(pane.querySelector("mark")?.textContent).toBe("Unused leave of up to 10 days carries over.");
    expect(passages.getPassage).not.toHaveBeenCalled();
  });

  it("opens as a sheet on narrower screens", async () => {
    screenWidth(false);
    passages.getPassage.mockResolvedValue({ ok: true, value: null });
    const user = userEvent.setup();
    render(<Conversation conversationId="c1" initialTurns={[SAVED]} />);

    await user.click(screen.getByRole("button", { name: "Source 1, leave.pdf, page 9" }));

    const sheet = await screen.findByRole("dialog", { name: "leave.pdf" });
    expect(sheet.querySelector("mark")).toBeTruthy();
    expect(await screen.findByText(/isn’t available any more/)).toBeTruthy();
  });

  it("shows the passage at once for an answer that just streamed in", async () => {
    screenWidth(true);
    passages.getPassage.mockResolvedValue({ ok: false, message: "Your session has expired." });
    const streamed: Turn = {
      ...SAVED,
      sources: [{ ...SAVED.sources[0], passage: "Unused leave of up to 10 days carries over." }],
    };
    const user = userEvent.setup();
    render(<Conversation conversationId="c1" initialTurns={[streamed]} />);

    await user.click(screen.getByRole("button", { name: "Source 1, leave.pdf, page 9" }));

    const pane = screen.getByRole("complementary", { name: "Source" });
    expect(pane.querySelector("mark")?.textContent).toBe("Unused leave of up to 10 days carries over.");
    expect((await screen.findByRole("alert")).textContent).toBe("Your session has expired.");
    expect(screen.queryByText("Loading the passage…")).toBeNull();
  });
});
