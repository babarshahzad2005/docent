"use client";

import { MenuIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

/** On screens narrower than 1024px, the Library navigation lives in a drawer. */
export function LibraryDrawer({ children }: { children: ReactNode }) {
  return (
    <Sheet>
      <SheetTrigger
        render={<Button variant="ghost" size="icon-lg" aria-label="Open library" />}
      >
        <MenuIcon aria-hidden="true" />
      </SheetTrigger>
      <SheetContent side="left" className="w-[17.5rem] gap-0 bg-background p-4 pt-5">
        <SheetTitle className="mb-6 px-2 font-serif text-wordmark font-medium">Docent</SheetTitle>
        <nav aria-label="Library" className="flex flex-1 flex-col">
          {children}
        </nav>
      </SheetContent>
    </Sheet>
  );
}
