import { NextResponse, type NextRequest } from "next/server";

import { safeNext } from "@/lib/safe-next";
import { createClient } from "@/lib/supabase/server";

export async function POST(request: NextRequest) {
  const supabase = await createClient();
  // This browser only; other devices stay signed in.
  await supabase.auth.signOut({ scope: "local" });
  // Optionally back to a page after signing in again, e.g. an invite opened as the wrong User.
  const form = await request.formData().catch(() => null);
  const next = safeNext(form?.get("next")?.toString());
  const signIn = new URL("/sign-in", request.nextUrl.origin);
  if (next !== "/") signIn.searchParams.set("next", next);
  return NextResponse.redirect(signIn, { status: 303 });
}
