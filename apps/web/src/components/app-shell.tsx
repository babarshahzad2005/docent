import { Suspense, type ReactNode } from "react";

import { ApiStatusMessage } from "@/app/api-status";

import { LibraryDrawer } from "./library-drawer";
import { LibraryNav } from "./library-nav";
import { Wordmark } from "./wordmark";

/**
 * The frame from DESIGN.md › Layout: Library navigation and the main area. Below 1024px the
 * navigation moves into a drawer. Conversations add the source pane beside their answers.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh">
      {/* Stays in view while the page scrolls; scrolls itself if its list is long. */}
      <nav
        aria-label="Library"
        className="sticky top-0 hidden h-dvh w-62 shrink-0 flex-col gap-6 overflow-y-auto border-r px-4 py-6 lg:flex"
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
        <Suspense fallback={null}>
          <ApiStatusMessage />
        </Suspense>
      </div>

    </div>
  );
}

