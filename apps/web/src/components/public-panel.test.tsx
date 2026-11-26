// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

const actions = vi.hoisted(() => ({ setCollectionPublic: vi.fn() }));
vi.mock("@/app/collections-actions", () => actions);
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { embedSnippet, PublicPanel } from "./public-panel";

const ID = "7b0e2f4a-1c3d-4e5f-8a9b-0c1d2e3f4a5b";

beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("The embed snippet", () => {
  it("is one script tag naming the loader and the collection", () => {
    expect(embedSnippet("https://docent.example", ID)).toBe(
      `<script src="https://docent.example/widget.js" data-collection="${ID}" async></script>`,
    );
  });

  it("is offered to copy once the collection is public", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { container } = render(
      <PublicPanel collectionId={ID} initial={{ public: true, public_until: null }} />,
    );

    const snippet = screen.getByRole("textbox", { name: "Add to a website" });
    expect((snippet as HTMLTextAreaElement).value).toBe(embedSnippet(window.location.origin, ID));
    await userEvent.click(screen.getByRole("button", { name: "Copy snippet" }));
    expect(writeText).toHaveBeenCalledWith(embedSnippet(window.location.origin, ID));
    expect(screen.getByText("Embed snippet copied.")).toBeTruthy();
    expect((await axe(container)).violations).toEqual([]);
  });

  it("isn't shown while the collection is private", () => {
    render(<PublicPanel collectionId={ID} initial={{ public: false, public_until: null }} />);

    expect(screen.queryByRole("textbox", { name: "Add to a website" })).toBeNull();
  });
});
