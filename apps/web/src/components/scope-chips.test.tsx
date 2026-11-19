// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { ScopeChips, scopeNames } from "./scope-chips";

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

    await userEvent.click(screen.getByRole("button", { name: "Don’t ask Personal" }));
    expect(screen.getByRole("status").textContent).toBe("d");
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
