import type { Metadata } from "next";
import { Suspense } from "react";

import { getDemoCollection } from "@/app/public-actions";
import { PublicCollectionView } from "@/components/public-collection-view";

export const metadata: Metadata = { title: "Try the demo · Docent" };

/**
 * The Demo Collection, open to anyone without signing in (GLOSSARY: Demo Collection; #95).
 * Offered as "Try the demo" on the sign-in page, which is the signed-out home page.
 */
export default function DemoPage() {
  return (
    <Suspense
      fallback={
        <p role="status" className="p-6 text-muted-foreground">
          Opening the demo…
        </p>
      }
    >
      <Demo />
    </Suspense>
  );
}

async function Demo() {
  const collection = await getDemoCollection();
  if (!collection) {
    // Only before the Demo Collection is seeded (a new environment).
    return (
      <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-4 px-4 py-12">
        <h1 className="font-serif text-question font-medium text-balance">
          The demo isn’t available right now
        </h1>
        <p className="text-pretty">Try again later, or sign in to ask your own documents.</p>
      </main>
    );
  }
  return <PublicCollectionView collection={collection} demo />;
}
