import { UploadIcon } from "lucide-react";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { getMe } from "@/lib/me";

export default function LibraryPage() {
  return (
    <AppShell>
      <Suspense fallback={<p role="status" className="p-6 text-muted-foreground">Loading your library…</p>}>
        <Library />
      </Suspense>
    </AppShell>
  );
}

async function Library() {
  const me = await getMe();
  // The API didn't accept the session: ask for a fresh sign-in (the error flag stops the
  // proxy from sending a still-signed-in browser straight back here).
  if (!me) redirect("/sign-in?error=session");

  const personal = me.collections.find((collection) => collection.is_personal);

  return (
    <div className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-4 px-4 py-12 text-center">
      <h1 className="font-serif text-question font-medium text-balance">Your library is empty</h1>
      <p className="text-muted-foreground">
        Docent answers questions only from documents you add. Upload PDFs, Word documents,
        Markdown, or plain text{personal ? ` to your ${personal.name} collection` : ""} to get
        started.
      </p>
      <Button size="lg" className="mt-2">
        <UploadIcon aria-hidden="true" />
        Upload documents
      </Button>
    </div>
  );
}
