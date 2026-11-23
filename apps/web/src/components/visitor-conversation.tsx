"use client";

import { type ReactNode, useCallback } from "react";

import { getPublicPassage } from "@/app/public-actions";
import { Conversation } from "@/components/conversation";
import { PassageLoaderContext } from "@/components/source-pane";

/** A Visitor asking one Public Collection: its Citations open its own passages. */
export function VisitorConversation({
  collectionId,
  apiUrl,
  intro,
}: {
  collectionId: string;
  /** Where the browser asks: the API itself (see Conversation's `visitor`). */
  apiUrl: string;
  intro: ReactNode;
}) {
  // Stable, so an open source isn't loaded again on every render.
  const load = useCallback(
    (chunkId: string) => getPublicPassage(collectionId, chunkId),
    [collectionId],
  );
  return (
    <PassageLoaderContext value={load}>
      <Conversation
        conversationId={null}
        initialTurns={[]}
        visitor={{ collectionId, apiUrl }}
        intro={intro}
      />
    </PassageLoaderContext>
  );
}
