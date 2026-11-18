"use client";

import { usePathname } from "next/navigation";
import { type ReactNode, useState } from "react";

import { AskBox } from "@/components/ask-box";
import { Conversation } from "@/components/conversation";

/**
 * A Collection's page with a question box above it; asking opens a new Conversation in its
 * place, answered from that Collection only (its Scope).
 */
export function LibraryHome({
  collectionId,
  label,
  children,
}: {
  collectionId: string;
  label: string;
  children: ReactNode;
}) {
  const [question, setQuestion] = useState<string | null>(null);
  const pathname = usePathname();

  // Asking moves the address to the new Conversation; coming back to this page (its link,
  // or Back) shows the page again. (Adjusted while rendering, as React recommends.)
  const [home] = useState(pathname);
  const [shownPath, setShownPath] = useState(pathname);
  if (pathname !== shownPath) {
    setShownPath(pathname);
    if (pathname === home) setQuestion(null);
  }

  if (question !== null) {
    return (
      <Conversation
        conversationId={null}
        initialTurns={[]}
        startQuestion={question}
        scope={[collectionId]}
      />
    );
  }
  return (
    <>
      <div className="mx-auto w-full max-w-3xl px-4 pt-8 sm:px-6">
        <AskBox
          label={label}
          placeholder={`${label}…`}
          onAsk={setQuestion}
        />
      </div>
      {children}
    </>
  );
}
