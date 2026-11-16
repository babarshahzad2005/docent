import type { ReactNode } from "react";

import { LibraryDrawer } from "./library-drawer";
import { LibraryNav } from "./library-nav";
import { Wordmark } from "./wordmark";

/**
 * The three-pane frame from DESIGN.md › Layout: Library navigation, the main area,
 * and the source pane. Below 1024px the navigation moves into a drawer.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh">
      <nav
        aria-label="Library"
        className="hidden w-62 shrink-0 flex-col gap-6 border-r px-4 py-6 lg:flex"
      >
        <Wordmark />
        <LibraryNav />
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b px-2 py-1 lg:hidden">
          <LibraryDrawer>
            <LibraryNav />
          </LibraryDrawer>
          <Wordmark />
        </header>
        <main className="flex flex-1 flex-col">{children}</main>
      </div>

      <SourcePane />
    </div>
  );
}

/** Shows a cited passage beside the answer. Closed until a Citation is opened (M2). */
function SourcePane() {
  return (
    <aside
      aria-label="Source"
      hidden
      className="w-105 shrink-0 border-l bg-surface xl:flex"
    />
  );
}
