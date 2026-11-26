import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { supabaseEnv } from "@/lib/supabase/env";

/** Pages anyone can open without signing in. */
const PUBLIC_PATHS = ["/sign-in", "/auth", "/privacy", "/public", "/demo", "/embed", "/widget.js"];

function isPublic(pathname: string) {
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

/**
 * Refreshes the Supabase session on every request and keeps signed-out visitors on the
 * public pages. The session is verified with getClaims(), which checks the token's signature.
 */
export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  let signedIn = false;

  const env = supabaseEnv();
  if (env) {
    const supabase = createServerClient(env.url, env.publishableKey, {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll(cookiesToSet, headers) {
          for (const { name, value } of cookiesToSet) request.cookies.set(name, value);
          response = NextResponse.next({ request });
          for (const { name, value, options } of cookiesToSet) {
            response.cookies.set(name, value, options);
          }
          // A response carrying a session must never be cached and served to someone else.
          for (const [key, value] of Object.entries(headers ?? {})) {
            response.headers.set(key, value);
          }
        },
      },
    });
    const { data } = await supabase.auth.getClaims();
    signedIn = Boolean(data?.claims);
  }

  const { pathname, search } = request.nextUrl;

  if (!signedIn && !isPublic(pathname)) {
    const signIn = request.nextUrl.clone();
    signIn.pathname = "/sign-in";
    signIn.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname + search)}`;
    return withCookies(NextResponse.redirect(signIn), response);
  }

  // A signed-in visitor doesn't need the sign-in page — unless the API rejected their session,
  // in which case the Library sent them here with ?error and bouncing back would loop forever.
  if (signedIn && pathname === "/sign-in" && !request.nextUrl.searchParams.has("error")) {
    const library = request.nextUrl.clone();
    library.pathname = "/";
    library.search = "";
    return withCookies(NextResponse.redirect(library), response);
  }

  return response;
}

/** Carry refreshed session cookies over to a redirect. */
function withCookies(redirect: NextResponse, from: NextResponse) {
  for (const cookie of from.cookies.getAll()) redirect.cookies.set(cookie);
  for (const header of ["cache-control", "expires", "pragma"]) {
    const value = from.headers.get(header);
    if (value) redirect.headers.set(header, value);
  }
  return redirect;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
