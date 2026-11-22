import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { acceptInvite } from "@/app/collections-actions";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Invite · Docent" };

/**
 * An invite's link (FLOWS › Share). Signed out, the proxy sends people to sign in first and
 * back here after. Signed in as the invited address, they join and land in the Collection;
 * otherwise the page says why, and what to do.
 */
export default function InvitePage({ params }: PageProps<"/invites/[id]">) {
  return (
    <AppShell>
      <Suspense
        fallback={<p role="status" className="p-6 text-muted-foreground">Opening the invite…</p>}
      >
        <Invite params={params} />
      </Suspense>
    </AppShell>
  );
}

async function Invite({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const accepted = await acceptInvite(id);
  if (accepted.ok) redirect(`/collections/${accepted.value.id}`);

  return (
    <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-4 px-4 py-12">
      <h1 className="font-serif text-question font-medium text-balance">
        This invite can’t be opened
      </h1>
      <p role="alert" className="text-pretty">
        {accepted.message}
      </p>
      {"wrongAccount" in accepted && (
        <form action="/auth/sign-out" method="post">
          <input type="hidden" name="next" value={`/invites/${id}`} />
          <Button type="submit">Sign out and use another account</Button>
        </form>
      )}
      <p>
        <Link
          href="/"
          className="text-brand underline underline-offset-2 [@media(hover:hover)_and_(pointer:fine)]:hover:text-brand-strong"
        >
          Go to your library
        </Link>
      </p>
    </div>
  );
}
