import type { Metadata } from "next";
import Link from "next/link";

import { getPublicCollection } from "@/app/public-actions";
import { VisitorConversation } from "@/components/visitor-conversation";
import { Wordmark } from "@/components/wordmark";
import { formatLocalDate } from "@/lib/dates";

const LINK =
  "text-brand underline underline-offset-2 [@media(hover:hover)_and_(pointer:fine)]:hover:text-brand-strong";

export async function generateMetadata({ params }: PageProps<"/public/[id]">): Promise<Metadata> {
  const collection = await getPublicCollection((await params).id);
  return {
    title: collection ? `${collection.name} · Docent` : "Unavailable · Docent",
    robots: { index: false }, // shared by link, not meant for search engines
  };
}

/**
 * A Public Collection's link (FLOWS › Publish): anyone can ask it without signing in, and
 * answers come only from its Documents. Off or expired, it says so.
 */
export default async function PublicCollectionPage({ params }: PageProps<"/public/[id]">) {
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

  return (
    <main className="flex min-h-dvh flex-col">
      <VisitorConversation
        collectionId={collection.id}
        intro={
          <header className="flex flex-col gap-4">
            <Link href="/" aria-label="Docent home" className="-ml-2 self-start">
              <Wordmark />
            </Link>
            <div className="flex flex-col gap-2">
              <h1 className="font-serif text-question font-medium text-balance">
                {collection.name}
              </h1>
              <p className="text-pretty text-text-secondary">
                Ask a question. Docent answers only from this collection’s documents, and shows
                where each answer comes from.
              </p>
              <p className="text-meta text-pretty text-muted-foreground">
                {collection.public_until &&
                  `Shared until ${formatLocalDate(collection.public_until)}. `}
                Nothing you ask is linked to you; questions are kept for up to 90 days to improve
                answers.{" "}
                <Link href="/privacy" className={LINK}>
                  Privacy
                </Link>
              </p>
            </div>
          </header>
        }
      />
    </main>
  );
}
