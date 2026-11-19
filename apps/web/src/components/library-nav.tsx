import Link from "next/link";
import { Suspense } from "react";

import { Button } from "@/components/ui/button";

import { CollectionsNav } from "./collections-nav";
import { ConversationsNav } from "./conversations-nav";

/** Navigation for the Library, shared by the sidebar and the drawer on smaller screens. */
export function LibraryNav() {
  return (
    <div className="flex flex-1 flex-col gap-6">
      <Link
        href="/"
        aria-current="page"
        className="rounded-md bg-muted px-2 py-2 font-medium text-foreground"
      >
        Library
      </Link>
      <Suspense fallback={null}>
        <CollectionsNav />
      </Suspense>
      <Suspense fallback={null}>
        <ConversationsNav />
      </Suspense>
      <form action="/auth/sign-out" method="post" className="mt-auto">
        <Button type="submit" variant="ghost" className="w-full justify-start px-2">
          Sign out
        </Button>
      </form>
    </div>
  );
}
