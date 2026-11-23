import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { getPublicCollection } from "@/app/public-actions";
import { PublicCollectionView } from "@/components/public-collection-view";
import { Wordmark } from "@/components/wordmark";

export const metadata: Metadata = {
  title: "Ask a collection · Docent",
  robots: { index: false }, // shared by link, not meant for search engines
};

/**
 * A Public Collection's link (FLOWS › Publish): anyone can ask it without signing in, and
 * answers come only from its Documents. Off or expired, it says so.
 */
export default function PublicCollectionPage({ params }: PageProps<"/public/[id]">) {
  return (
    <Suspense
      fallback={
        <p role="status" className="p-6 text-muted-foreground">
          Opening the collection…
        </p>
      }
    >
      <PublicCollection params={params} />
    </Suspense>
  );
}

async function PublicCollection({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const collection = await getPublicCollection(id);
  if (!collection) {
    return (
      <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-4 px-4 py-12">
        <Link href="/" aria-label="Docent home" className="-ml-2 self-start">
          <Wordmark />
        </Link>
        <h1 className="font-serif text-question font-medium text-balance">
          This collection isn’t available
        </h1>
        <p className="text-pretty">
          Its owner may have stopped sharing it, or the link has expired. Ask them for a new link.
        </p>
      </main>
    );
  }
  return <PublicCollectionView collection={collection} />;
}
