import type { Metadata } from "next";
import { notFound } from "next/navigation";
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
  if (!collection) notFound();
  return <PublicCollectionView collection={collection} demo />;
}
