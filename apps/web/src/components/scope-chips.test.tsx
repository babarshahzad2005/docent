// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { defaultScope, ScopeChips, scopeNames } from "./scope-chips";

const COLLECTIONS = [
  { id: "p", name: "Personal" },
  { id: "d", name: "Demo Collection" },
];

function Picker({ start }: { start: string[] }) {
  const [scope, setScope] = useState(start);
  return (
    <>
      <ScopeChips collections={COLLECTIONS} value={scope} onChange={setScope} />
      <output>{scope.join(",")}</output>
    </>
  );
}

afterEach(cleanup);

describe("ScopeChips", () => {
  it("adds and removes Collections, always leaving one", async () => {
    const { container } = render(<Picker start={["p"]} />);

    expect(screen.queryByRole("button", { name: "Don’t ask Personal" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Add a collection" }));
    await userEvent.click(screen.getByRole("button", { name: "Demo Collection" }));
    expect(screen.getByRole("status").textContent).toBe("p,d");
    expect(screen.queryByRole("button", { name: "Add a collection" })).toBeNull();

    expect(document.activeElement?.getAttribute("aria-label")).toBe("Don’t ask Personal");
    await userEvent.click(screen.getByRole("button", { name: "Don’t ask Personal" }));
    expect(screen.getByRole("status").textContent).toBe("d");
    // The button used is gone; focus stays in the chips, on "Add a collection".
    expect(document.activeElement?.textContent).toBe("Add a collection");
    const results = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});

describe("scopeNames", () => {
  it("names the Scope an answer used", () => {
    expect(scopeNames(["p"], COLLECTIONS)).toBe("Personal");
    expect(scopeNames(["p", "d"], COLLECTIONS)).toBe("Personal and Demo Collection");
    expect(scopeNames(["gone"], COLLECTIONS)).toBeNull();
  });
});

describe("defaultScope", () => {
  it("is the User's own Collections, offering the Demo Collection rather than choosing it", () => {
    const withDemo = [
      { id: "p", name: "Personal" },
      { id: "s", name: "Shared" },
      { id: "d", name: "Demo Collection", is_demo: true },
    ];

    expect(defaultScope(withDemo)).toEqual(["p", "s"]);
    expect(defaultScope([withDemo[2]])).toEqual(["d"]); // unless it is all there is
  });
});
