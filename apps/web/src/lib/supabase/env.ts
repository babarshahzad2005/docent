/** Public Supabase settings. Both values are safe to expose to the browser. */
export function supabaseEnv(): { url: string; publishableKey: string } | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  return url && publishableKey ? { url, publishableKey } : null;
}

export function requireSupabaseEnv() {
  const env = supabaseEnv();
  if (!env) {
    throw new Error(
      "Sign-in isn't configured: set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY.",
    );
  }
  return env;
}
