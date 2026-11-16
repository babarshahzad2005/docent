import "server-only";

import { createDocentClient } from "@docent/client";
import { connection } from "next/server";
import { cache } from "react";

import { apiBaseUrl } from "@/lib/api-status";
import { createClient } from "@/lib/supabase/server";

/**
 * The signed-in User and their Collections, from the API. Returns null when there is no valid
 * session. Cached per request so the navigation and the page share one API call.
 *
 * The access token is read from the session cookie and forwarded as-is: the API verifies its
 * signature itself, so nothing here trusts the cookie's contents.
 */
export const getMe = cache(async () => {
  // Request-time only: the Supabase client reads the clock while loading the session.
  await connection();
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) return null;

  const { data, response } = await createDocentClient(apiBaseUrl()).GET("/me", {
    headers: { Authorization: `Bearer ${session.access_token}` },
  });
  if (response.status === 401) return null;
  if (!data) throw new Error(`The server answered with status ${response.status}.`);
  return data;
});
