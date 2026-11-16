import { createDocentClient } from "@docent/client";
import { describe, expect, it } from "vitest";

import { getApiStatus } from "./api-status";

function clientReturning(fetchImpl: typeof fetch) {
  return createDocentClient("http://api.test", { fetch: fetchImpl });
}

describe("getApiStatus", () => {
  it("reports connected with the version when the API is healthy", async () => {
    const client = clientReturning(async () =>
      Response.json({ status: "ok", version: "1.2.3" }),
    );

    await expect(getApiStatus(client)).resolves.toEqual({ kind: "connected", version: "1.2.3" });
  });

  it("reports unreachable when the API returns an error status", async () => {
    const client = clientReturning(async () => new Response("down", { status: 503 }));

    await expect(getApiStatus(client)).resolves.toEqual({
      kind: "unreachable",
      reason: "The API answered with status 503.",
    });
  });

  it("reports unreachable when the request fails", async () => {
    const client = clientReturning(async () => {
      throw new TypeError("fetch failed");
    });

    await expect(getApiStatus(client)).resolves.toEqual({
      kind: "unreachable",
      reason: "The API didn't respond.",
    });
  });
});
