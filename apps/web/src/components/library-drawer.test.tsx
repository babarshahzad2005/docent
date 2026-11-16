// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { LibraryDrawer } from "./library-drawer";

afterEach(cleanup);

describe("LibraryDrawer", () => {
  it("opens by keyboard, is accessible, and returns focus when closed", async () => {
    const user = userEvent.setup();
    render(
      <LibraryDrawer>
        <a href="#collections">Collections</a>
      </LibraryDrawer>,
    );

    const trigger = screen.getByRole("button", { name: "Open library" });
    trigger.focus();
    await user.keyboard("{Enter}");

    const drawer = await screen.findByRole("dialog", { name: "Library" });
    expect(screen.getByRole("navigation", { name: "Library" })).toBeTruthy();

    // jsdom can't compute colors; contrast is covered by the browser tests on the same tokens.
    const results = await axe(drawer, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });
});
