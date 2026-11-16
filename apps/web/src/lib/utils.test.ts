import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("cn", () => {
  it("keeps a type-scale size and a text color together", () => {
    expect(cn("text-primary-foreground", "text-ui")).toBe("text-primary-foreground text-ui");
  });

  it("still lets a later size replace an earlier one", () => {
    expect(cn("text-ui", "text-meta")).toBe("text-meta");
  });
});
