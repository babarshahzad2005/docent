import { describe, expect, it } from "vitest";

import { safeNext } from "./safe-next";

describe("safeNext", () => {
  it("keeps paths inside Docent", () => {
    expect(safeNext("/")).toBe("/");
    expect(safeNext("/collections/123?tab=documents#top")).toBe("/collections/123?tab=documents#top");
  });

  it.each([
    ["missing", null],
    ["empty", ""],
    ["another site", "https://evil.example"],
    ["protocol-relative", "//evil.example"],
    ["backslash trick", "/\\evil.example"],
    ["tab trick", "/\t/evil.example"],
    ["newline trick", "/\n/evil.example"],
    ["carriage-return trick", "/\r//evil.example"],
    ["script URL", "javascript:alert(1)"],
    ["relative path", "collections"],
  ])("falls back to the Library for %s", (_label, next) => {
    expect(safeNext(next)).toBe("/");
  });
});
