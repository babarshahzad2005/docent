"use client";

import { Button } from "@/components/ui/button";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="font-serif text-question font-medium">Docent can&rsquo;t load right now</h1>
      <p className="text-muted-foreground">
        The server didn&rsquo;t respond. It may be starting up; try again in a minute.
      </p>
      <Button size="lg" onClick={reset}>
        Try again
      </Button>
    </main>
  );
}
