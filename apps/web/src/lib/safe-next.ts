const PLACEHOLDER_ORIGIN = "https://docent.invalid";

/**
 * Where to send someone after sign-in. Only paths inside Docent are allowed, so a crafted
 * link can't redirect a signed-in user to another site.
 *
 * The check resolves the value the same way the redirect will (URL parsing strips tabs and
 * newlines, so "/\t/evil.example" would otherwise become "//evil.example").
 */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/")) return "/";
  try {
    const url = new URL(next, PLACEHOLDER_ORIGIN);
    if (url.origin !== PLACEHOLDER_ORIGIN) return "/";
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "/";
  }
}
