import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";

import { listDocuments } from "@/app/documents-actions";
import { AppShell } from "@/components/app-shell";
import { CollectionSettings } from "@/components/collection-settings";
import { LibraryDocuments } from "@/components/library-documents";
import { LibraryHome } from "@/components/library-home";
import { getMe } from "@/lib/me";

export const metadata: Metadata = { title: "Collection · Docent" };

export default function CollectionPage({ params }: PageProps<"/collections/[id]">) {
  return (
    <AppShell>
      <Suspense
        fallback={<p role="status" className="p-6 text-muted-foreground">Loading the collection…</p>}
      >
        <Collection params={params} />
      </Suspense>
    </AppShell>
  );
}

async function Collection({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const me = await getMe();
  if (!me) redirect("/sign-in?error=session");
  const collection = me.collections.find((c) => c.id === id);
  if (!collection) notFound();
  if (collection.is_personal) redirect("/");
  const documents = await listDocuments();
  if (!documents.ok) throw new Error(documents.message);

  return (
    <LibraryHome
      collections={me.collections}
      defaultScope={[collection.id]}
      label={`Ask a question about the ${collection.name}`}
    >
      <LibraryDocuments
        collection={collection}
        initialDocuments={documents.value}
        settings={
          collection.role === "owner" &&
          !collection.is_demo && (
            <CollectionSettings
              collection={collection}
              documentCount={
                documents.value.filter((document) => document.collection_id === collection.id)
                  .length
              }
            />
          )
        }
      />
    </LibraryHome>
  );
}
