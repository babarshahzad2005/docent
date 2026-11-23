// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

const actions = vi.hoisted(() => ({ getPublicPassage: vi.fn(), getPassage: vi.fn() }));
vi.mock("@/app/public-actions", () => ({ getPublicPassage: actions.getPublicPassage }));
vi.mock("@/app/passages-actions", () => ({ getPassage: actions.getPassage }));

import { VisitorConversation } from "./visitor-conversation";

function sse(...events: [string, object][]): Response {
  const body = events
    .map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}

const START = {
  conversation_id: null,
  message_id: null,
  sources: [
    {
      number: 1,
      chunk_id: "k1",
      document_id: "d1",
      document_name: "leave.pdf",
      heading_path: ["Leave"],
      page: 9,
      passage: "Up to 10 days carry over.",
    },
  ],
};

beforeEach(() => {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: true,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

describe("A Visitor on a Public Collection's page", () => {
  it("asks that Collection only, saves nothing, and opens its passages", async () => {
    const fetch = vi.fn().mockResolvedValue(
      sse(
        ["start", START],
        ["delta", { text: "Up to 10 days [1]." }],
        [
          "done",
          {
            message_id: null,
            outcome: "answered",
            cited: [1],
            answer: "Up to 10 days [1].",
            verified: true,
            removed: [],
          },
        ],
      ),
    );
    vi.stubGlobal("fetch", fetch);
    actions.getPublicPassage.mockResolvedValue({
      ok: true,
      value: {
        chunk_id: "k1",
        document_id: "d1",
        document_name: "leave.pdf",
        heading_path: ["Leave"],
        page: 9,
        content: "Up to 10 days carry over.",
        replaced: false,
        before: null,
        after: null,
      },
    });
    const path = window.location.pathname;
    const { container } = render(
      <VisitorConversation
        collectionId="pub-1"
        apiUrl="https://api.example"
        intro={<h1>Staff handbook</h1>}
      />,
    );

    await userEvent.type(screen.getByRole("textbox", { name: "Ask a question" }), "Leave?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    const citation = await screen.findByRole("button", { name: "Source 1, leave.pdf, page 9" });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("https://api.example/public/pub-1/answers"); // straight to the API
    expect(JSON.parse(init.body)).toEqual({ question: "Leave?" });
    expect(window.location.pathname).toBe(path); // no Conversation to go to
    // The Collection's name is the page's heading; the question sits under it.
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Leave?");
    expect(screen.queryByRole("group", { name: /collections/i })).toBeNull(); // no Scope chips
    expect(screen.getByRole("textbox", { name: "Ask another question" })).toBeTruthy();

    await userEvent.click(citation);
    await waitFor(() => expect(actions.getPublicPassage).toHaveBeenCalledWith("pub-1", "k1"));
    expect(actions.getPassage).not.toHaveBeenCalled();
    const results = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });

  it("calls a Decline's passages the Collection's, not theirs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sse(
          ["start", START],
          ["delta", { text: "I couldn’t find that in this collection’s documents." }],
          [
            "done",
            {
              message_id: null,
              outcome: "declined",
              cited: [1],
              answer: "I couldn’t find that in this collection’s documents.",
              verified: false,
              removed: [],
            },
          ],
        ),
      ),
    );
    render(<VisitorConversation collectionId="pub-1" apiUrl="https://api.example" intro={null} />);

    await userEvent.type(screen.getByRole("textbox", { name: "Ask a question" }), "Parking?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("The closest passages in its documents:")).toBeTruthy();
    expect(screen.queryByText(/your library/)).toBeNull();
  });

  it("says when to ask again after too many questions", async () => {
    const wait = "You’ve asked a lot of questions in a short time. Try again in 12 minutes.";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({ detail: wait }, { status: 429, headers: { "Retry-After": "700" } }),
      ),
    );
    render(<VisitorConversation collectionId="pub-1" apiUrl="https://api.example" intro={null} />);

    await userEvent.type(screen.getByRole("textbox", { name: "Ask a question" }), "Leave?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect((await screen.findByRole("alert")).textContent).toContain(wait);
  });
});
