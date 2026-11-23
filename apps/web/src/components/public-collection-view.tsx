import Link from "next/link";

import type { PublicCollection } from "@/app/public-actions";
import { VisitorConversation } from "@/components/visitor-conversation";
import { Wordmark } from "@/components/wordmark";
import { apiBaseUrl } from "@/lib/api-status";
import { formatLocalDate } from "@/lib/dates";

const LINK =
  "text-brand underline underline-offset-2 [@media(hover:hover)_and_(pointer:fine)]:hover:text-brand-strong";

/**
 * A Public Collection as a Visitor sees it (FLOWS › Publish): its name, what Docent does, and
 * a box to ask it. The Demo Collection's page also invites them to sign in for their own.
 */
export function PublicCollectionView({
  collection,
  demo = false,
}: {
  collection: PublicCollection;
  demo?: boolean;
}) {
  return (
    <main className="flex min-h-dvh flex-col">
      <title>{`${collection.name} · Docent`}</title>
      <VisitorConversation
        collectionId={collection.id}
        apiUrl={apiBaseUrl()}
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
                {demo
                  ? "Try Docent on a collection of openly licensed documents: staff handbooks and public guidance. Ask a question, and Docent answers only from them, showing where each answer comes from."
                  : "Ask a question. Docent answers only from this collection’s documents, and shows where each answer comes from."}
              </p>
              {demo && (
                <p className="text-pretty">
                  <Link href="/sign-in" className={LINK}>
                    Sign in to ask your own documents
                  </Link>
                </p>
              )}
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
