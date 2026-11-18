import { redirect } from "next/navigation";
import { Suspense } from "react";

import { listDocuments } from "@/app/documents-actions";
import { AppShell } from "@/components/app-shell";
import { LibraryDocuments } from "@/components/library-documents";
import { LibraryHome } from "@/components/library-home";
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
  if (!personal) throw new Error("Your Personal collection is missing.");
  const documents = await listDocuments();
  if (!documents.ok) throw new Error(documents.message);

  return (
    <LibraryHome collectionId={personal.id} label="Ask a question about your documents">
      <LibraryDocuments collection={personal} initialDocuments={documents.value} />
    </LibraryHome>
  );
}
