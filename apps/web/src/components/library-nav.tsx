import Link from "next/link";

/** Navigation for the Library, shared by the sidebar and the drawer on smaller screens. */
export function LibraryNav() {
  return (
    <Link
      href="/"
      aria-current="page"
      className="rounded-md bg-muted px-2 py-2 font-medium text-foreground"
    >
      Library
    </Link>
  );
}
