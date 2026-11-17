// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { Conversation } from "./conversation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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
  it("streams an answer, names its sources, and announces it once complete", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sse(
          ["start", START],
          ["delta", { text: "Up to 10 days " }],
          ["delta", { text: "carry over 【1】." }],
          ["done", { message_id: "m1", outcome: "answered", cited: [1] }],
        ),
      ),
    );
    const { container } = render(
      <Conversation conversationId={null} initialTurns={[]} startQuestion="How much carries over?" />,
    );

    const citation = await screen.findByRole("link", { name: "Source 1, leave.pdf, page 9" });
    expect(citation.textContent).toBe("1");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("How much carries over?");
    expect(screen.getByRole("list", { name: "Sources" }).textContent).toContain("Page 9");
    await waitFor(() =>
      expect(screen.getByText("Up to 10 days carry over .", { selector: "p" })).toBeTruthy(),
    );
    expect(window.location.pathname).toBe("/conversations/c1");
    const results = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
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
