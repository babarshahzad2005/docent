import Link from "next/link";
import { Suspense } from "react";

import { ApiStatusMessage } from "@/app/api-status";

/** Navigation for the Library, shared by the sidebar and the drawer on smaller screens. */
export function LibraryNav() {
  return (
    <div className="flex h-full flex-col gap-6">
      <Link
        href="/"
        aria-current="page"
        className="rounded-md bg-muted px-2 py-2 font-medium text-foreground"
      >
        Library
      </Link>

      <section aria-labelledby="collections-heading" className="flex flex-col gap-1">
        <h2 id="collections-heading" className="px-2 text-meta font-medium text-muted-foreground">
          Collections
        </h2>
        <p className="px-2 text-meta text-muted-foreground">
          Collections you create or are invited to appear here.
        </p>
      </section>

      <div className="mt-auto px-2 text-meta text-muted-foreground">
        <Suspense fallback={<p role="status">Checking the server…</p>}>
          <ApiStatusMessage />
        </Suspense>
      </div>
    </div>
  );
}
