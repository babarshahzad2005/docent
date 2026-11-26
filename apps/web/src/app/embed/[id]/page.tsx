import type { Metadata } from "next";
import { Suspense } from "react";

import { getPublicCollection } from "@/app/public-actions";
import { EmbedBridge } from "@/components/embed-bridge";
import { VisitorConversation } from "@/components/visitor-conversation";
import { apiBaseUrl } from "@/lib/api-status";

export const metadata: Metadata = {
  title: "Ask a collection · Docent",
  robots: { index: false },
};

const LINK =
  "text-brand underline underline-offset-2 [@media(hover:hover)_and_(pointer:fine)]:hover:text-brand-strong";

/**
 * The chat inside a Widget (GLOSSARY: Widget): a Public Collection asked from another
 * website, framed by public/widget.js. Off or expired, it says the Collection is unavailable.
 */
export default function EmbedPage({ params }: PageProps<"/embed/[id]">) {
  return (
    <>
      <EmbedBridge />
      <Suspense
        fallback={
          <p role="status" className="p-4 text-muted-foreground">
            Opening the chat…
          </p>
        }
      >
        <Embed params={params} />
      </Suspense>
    </>
  );
}

async function Embed({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const collection = await getPublicCollection(id);
  if (!collection) {
    return (
      <main className="flex min-h-dvh flex-col justify-center gap-3 px-4 py-8">
        <h1 className="font-serif text-heading font-medium text-balance">
          This collection isn’t available
        </h1>
        <p className="text-pretty">Its owner may have stopped sharing it. Try again later.</p>
      </main>
    );
  }
  return (
    <main className="flex min-h-dvh flex-col">
      <title>{`${collection.name} · Docent`}</title>
      <VisitorConversation
        collectionId={collection.id}
        apiUrl={apiBaseUrl()}
        intro={
          <header className="flex flex-col gap-2">
            <h1 className="font-serif text-heading font-medium text-balance">{collection.name}</h1>
            <p className="text-meta text-pretty text-text-secondary">
              Docent answers only from this collection’s documents, and shows where each answer
              comes from. Nothing you ask is linked to you; questions are kept for up to 90 days.{" "}
              <a href="/privacy" target="_blank" rel="noopener" className={LINK}>
                Privacy
              </a>
            </p>
          </header>
        }
      />
    </main>
  );
}
