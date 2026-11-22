import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";

import { listInvites, listMembers } from "@/app/collections-actions";
import { listDocuments } from "@/app/documents-actions";
import { AppShell } from "@/components/app-shell";
import { CollectionSettings } from "@/components/collection-settings";
import { LibraryDocuments } from "@/components/library-documents";
import { LibraryHome } from "@/components/library-home";
import { MemberSettings } from "@/components/members-list";
import { getMe } from "@/lib/me";
import { moveTargets } from "@/lib/scope";

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
  const owned = collection.role === "owner" && !collection.is_demo;
  const [documents, invites, members] = await Promise.all([
    listDocuments(),
    owned ? listInvites(collection.id) : null,
    // The Demo Collection's Members are every User: it has no list to show.
    collection.is_demo ? null : listMembers(collection.id),
  ]);
  if (!documents.ok) throw new Error(documents.message);
  if (invites && !invites.ok) throw new Error(invites.message);
  // Not fatal: removed meanwhile, the next load shows the Collection gone.
  const people = members?.ok ? members.value : [];

  return (
    <LibraryHome
      collections={me.collections}
      defaultScope={[collection.id]}
      label={`Ask a question about ${collection.is_demo ? "the " : ""}${collection.name}`}
    >
      <LibraryDocuments
        collection={collection}
        initialDocuments={documents.value}
        moveTargets={moveTargets(me.collections, collection.id)}
        settings={
          owned ? (
            <CollectionSettings
              collection={collection}
              invites={invites?.ok ? invites.value : []}
              members={people}
              documentCount={
                documents.value.filter((document) => document.collection_id === collection.id)
                  .length
              }
            />
          ) : (
            !collection.is_demo && <MemberSettings collection={collection} members={people} />
          )
        }
      />
    </LibraryHome>
  );
}
