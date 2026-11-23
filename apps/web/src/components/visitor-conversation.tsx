"use client";

import type { ReactNode } from "react";

import { getPublicPassage } from "@/app/public-actions";
import { Conversation } from "@/components/conversation";
import { PassageLoaderContext } from "@/components/source-pane";

/** A Visitor asking one Public Collection: its Citations open its own passages. */
export function VisitorConversation({
  collectionId,
  intro,
}: {
  collectionId: string;
  intro: ReactNode;
}) {
  return (
    <PassageLoaderContext value={(chunkId) => getPublicPassage(collectionId, chunkId)}>
      <Conversation
        conversationId={null}
        initialTurns={[]}
        visitor={{ collectionId }}
        intro={intro}
      />
    </PassageLoaderContext>
  );
}
