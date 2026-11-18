"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/** A navigation link that marks itself as the current page. */
export function NavLink({ href, children }: { href: string; children: ReactNode }) {
  const current = usePathname() === href;
  return (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      className="block rounded-md px-2 py-2 text-text-secondary aria-[current=page]:bg-muted aria-[current=page]:font-medium aria-[current=page]:text-foreground [@media(hover:hover)_and_(pointer:fine)]:hover:bg-muted"
    >
      {children}
    </Link>
  );
}
