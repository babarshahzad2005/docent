import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

import { requireSupabaseEnv } from "./env";

/** Supabase client for Server Components, Server Actions, and Route Handlers. */
export async function createClient() {
  const { url, publishableKey } = requireSupabaseEnv();
  const cookieStore = await cookies();

  return createServerClient(url, publishableKey, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // Server Components can't set cookies; the proxy refreshes the session instead.
        }
      },
    },
  });
}
