import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { AppShell } from "@/components/app-shell";
import { Conversation, type Turn } from "@/components/conversation";
import { apiAsUser } from "@/lib/api";

export const metadata: Metadata = { title: "Conversation · Docent" };

export default function ConversationPage({ params }: PageProps<"/conversations/[id]">) {
  return (
    <AppShell>
      <Suspense
        fallback={<p role="status" className="p-6 text-muted-foreground">Loading the conversation…</p>}
      >
        <SavedConversation params={params} />
      </Suspense>
    </AppShell>
  );
}

async function SavedConversation({ params }: { params: Promise<{ id: string }> }) {
  await connection();
  const { id } = await params;
  const caller = await apiAsUser();
  if (!caller) redirect(`/sign-in?next=/conversations/${encodeURIComponent(id)}`);
  const { data, response } = await caller.api.GET("/conversations/{conversation_id}", {
    headers: caller.headers,
    params: { path: { conversation_id: id } },
  });
  if (response.status === 404 || response.status === 422) notFound();
  if (response.status === 401) redirect("/sign-in?error=session");
  if (!data) throw new Error(`The server answered with status ${response.status}.`);

  // Messages alternate: each question, then its answer.
  const turns: Turn[] = [];
  let scope: string[] | undefined;
  for (const message of data.messages) {
    if (message.role === "user") {
      scope = message.scope; // follow-ups keep the Scope of the latest question
      turns.push({ question: message.content, answer: "", sources: [], cited: [], status: "complete" });
      continue;
    }
    const turn = turns[turns.length - 1];
    if (!turn) continue;
    turn.answer = message.content;
    turn.messageId = message.id;
    turn.sources = message.citations;
    turn.cited = message.citations.map((citation) => citation.number);
    turn.status = message.status === "streaming" ? "interrupted" : message.status;
    if (message.status === "interrupted") turn.error = "This answer was cut off. Ask again to get the whole answer.";
    if (message.status === "failed") turn.error = "Docent couldn’t answer this. Ask again.";
  }
  return <Conversation key={id} conversationId={id} initialTurns={turns} scope={scope} />;
}
