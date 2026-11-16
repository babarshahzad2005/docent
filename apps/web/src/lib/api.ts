import "server-only";

import { createDocentClient } from "@docent/client";

import { apiBaseUrl } from "@/lib/api-status";
import { createClient } from "@/lib/supabase/server";

/**
 * The Docent API, called as the signed-in User. Returns null when there is no session.
 *
 * The access token is read from the session cookie and forwarded as-is: the API verifies its
 * signature itself, so nothing here trusts the cookie's contents.
 */
export async function apiAsUser() {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) return null;
  return {
    api: createDocentClient(apiBaseUrl()),
    headers: { Authorization: `Bearer ${session.access_token}` },
  };
}
