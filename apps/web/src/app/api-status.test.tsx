import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiStatus } from "@/lib/api-status";

import { ApiStatusMessage } from "./api-status";

const status = vi.hoisted(() => ({ current: undefined as ApiStatus | undefined }));

vi.mock("next/server", () => ({ connection: async () => {} }));
vi.mock("@/lib/api-status", () => ({ getApiStatus: async () => status.current }));

async function renderMessage() {
  return renderToStaticMarkup(await ApiStatusMessage());
}

describe("ApiStatusMessage", () => {
  beforeEach(() => {
    status.current = undefined;
  });

  it("says the server is connected and shows its version", async () => {
    status.current = { kind: "connected", version: "0.1.0" };

    expect(await renderMessage()).toContain("Server connected (version 0.1.0)");
  });

  it("says the server can't be reached, with the reason as a tooltip", async () => {
    status.current = { kind: "unreachable", reason: "The API didn't respond." };

    const html = await renderMessage();
    expect(html).toContain("Can’t reach the server right now.");
    expect(html).toContain('title="The API didn&#x27;t respond."');
  });
});
