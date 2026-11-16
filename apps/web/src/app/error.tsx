"use client";

import { Button } from "@/components/ui/button";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="font-serif text-question font-medium">This page didn&rsquo;t load</h1>
      <p className="text-muted-foreground">
        Something went wrong while loading it. Try again; if it keeps happening, the server may be
        starting up or briefly unavailable, so wait a minute and try once more.
      </p>
      <Button size="lg" onClick={reset}>
        Try again
      </Button>
    </main>
  );
}
