import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { buttonVariants } from "@/components/ui/button";
import { Wordmark } from "@/components/wordmark";

import { SignInForm } from "./sign-in-form";

export const metadata: Metadata = { title: "Sign in · Docent" };

export default function SignInPage() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-4 py-12">
      <div className="flex w-full max-w-sm flex-col gap-8">
        <Wordmark />
        <div className="flex flex-col gap-2 px-2">
          <h1 className="font-serif text-question font-medium">Sign in</h1>
          <p className="text-muted-foreground">
            Ask questions of your documents and get answers that show where they came from.
          </p>
        </div>
        <div className="px-2">
          <Suspense fallback={null}>
            <SignInForm />
          </Suspense>
        </div>
        <div className="flex flex-col gap-2 border-t border-border px-2 pt-6">
          <p className="text-muted-foreground">Not ready to sign in?</p>
          <Link href="/demo" className={buttonVariants({ variant: "outline" })}>
            Try the demo
          </Link>
        </div>
        <p className="px-2 text-meta text-muted-foreground">
          What Docent stores and why is described in the{" "}
          <Link href="/privacy" className="underline underline-offset-2">
            privacy notice
          </Link>
          .
        </p>
      </div>
    </main>
  );
}
