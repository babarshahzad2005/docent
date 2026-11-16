/**
 * Where to send someone after sign-in. Only paths inside Docent are allowed, so a crafted
 * link can't redirect a signed-in user to another site.
 */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return "/";
  }
  return next;
}
