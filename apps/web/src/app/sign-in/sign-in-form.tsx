"use client";

import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { safeNext } from "@/lib/safe-next";
import { createClient } from "@/lib/supabase/client";

type State =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "sent"; email: string }
  | { kind: "error"; message: string };

const ERRORS: Record<string, string> = {
  link: "That sign-in link didn't work. It may have expired or already been used. Request a new one below.",
  session: "Your session couldn't be confirmed. Sign in again to continue.",
};

export function SignInForm() {
  const searchParams = useSearchParams();
  const next = safeNext(searchParams.get("next"));
  const error = searchParams.get("error");
  const [state, setState] = useState<State>(
    error ? { kind: "error", message: ERRORS[error] ?? ERRORS.link } : { kind: "idle" },
  );

  function callbackUrl() {
    return `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`;
  }

  async function continueWithGoogle() {
    setState({ kind: "sending" });
    const { error } = await createClient().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: callbackUrl() },
    });
    if (error) setState({ kind: "error", message: "Google sign-in didn't start. Try again." });
  }

  async function emailLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    setState({ kind: "sending" });
    const { error } = await createClient().auth.signInWithOtp({
      email,
      options: { emailRedirectTo: callbackUrl() },
    });
    setState(
      error
        ? {
            kind: "error",
            message:
              error.status === 429
                ? "Too many sign-in emails were sent recently. Wait a few minutes, then try again."
                : "We couldn't send the email. Check the address and try again.",
          }
        : { kind: "sent", email },
    );
  }

  if (state.kind === "sent") {
    return (
      <div role="status" className="flex flex-col gap-2">
        <h2 className="font-serif text-heading">Check your email</h2>
        <p className="text-muted-foreground">
          We sent a sign-in link to <strong className="font-medium text-foreground">{state.email}</strong>.
          Open it in this browser to continue. It expires in one hour.
        </p>
        <Button variant="ghost" className="self-start" onClick={() => setState({ kind: "idle" })}>
          Use a different email
        </Button>
      </div>
    );
  }

  const busy = state.kind === "sending";

  return (
    <div className="flex flex-col gap-6">
      {state.kind === "error" && (
        <p role="alert" className="rounded-lg border border-destructive/40 px-4 py-3 text-destructive">
          {state.message}
        </p>
      )}

      <Button variant="outline" size="lg" onClick={continueWithGoogle} disabled={busy}>
        <GoogleMark />
        Continue with Google
      </Button>

      <div className="flex items-center gap-3 text-meta text-muted-foreground" aria-hidden="true">
        <span className="h-px flex-1 bg-border" />
        or
        <span className="h-px flex-1 bg-border" />
      </div>

      <form onSubmit={emailLink} className="flex flex-col gap-3">
        <label htmlFor="email" className="font-medium">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          required
          autoComplete="email"
          placeholder="you@example.com"
          className="h-11 rounded-lg border border-input bg-surface px-3 text-base text-foreground"
        />
        <Button type="submit" size="lg" disabled={busy}>
          {busy ? "Sending…" : "Email me a sign-in link"}
        </Button>
      </form>
    </div>
  );
}

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.3-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.2-.1-2.3-.4-3.5z" />
    </svg>
  );
}
