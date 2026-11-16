import "server-only";

import { connection } from "next/server";
import { cache } from "react";

import { apiAsUser } from "@/lib/api";

/**
 * The signed-in User and their Collections, from the API. Returns null when there is no valid
 * session. Cached per request so the navigation and the page share one API call.
 */
export const getMe = cache(async () => {
  // Request-time only: the Supabase client reads the clock while loading the session.
  await connection();
  const caller = await apiAsUser();
  if (!caller) return null;

  const { data, response } = await caller.api.GET("/me", { headers: caller.headers });
  if (response.status === 401) return null;
  if (!data) throw new Error(`The server answered with status ${response.status}.`);
  return data;
});
