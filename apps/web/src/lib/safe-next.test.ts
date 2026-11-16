import { describe, expect, it } from "vitest";

import { safeNext } from "./safe-next";

describe("safeNext", () => {
  it("keeps paths inside Docent", () => {
    expect(safeNext("/")).toBe("/");
    expect(safeNext("/collections/123?tab=documents")).toBe("/collections/123?tab=documents");
  });

  it.each([
    ["missing", null],
    ["empty", ""],
    ["another site", "https://evil.example"],
    ["protocol-relative", "//evil.example"],
    ["backslash trick", "/\\evil.example"],
    ["relative path", "collections"],
  ])("falls back to the Library for %s", (_label, next) => {
    expect(safeNext(next)).toBe("/");
  });
});
