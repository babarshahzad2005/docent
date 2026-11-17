"use client";

import { type ReactNode, useState } from "react";

import { AskBox } from "@/components/ask-box";
import { Conversation } from "@/components/conversation";

/** The Library with a question box above it; asking opens a new Conversation in its place. */
export function LibraryHome({ children }: { children: ReactNode }) {
  const [question, setQuestion] = useState<string | null>(null);

  if (question !== null) {
    return <Conversation conversationId={null} initialTurns={[]} startQuestion={question} />;
  }
  return (
    <>
      <div className="mx-auto w-full max-w-3xl px-4 pt-8 sm:px-6">
        <AskBox
          label="Ask a question about your documents"
          placeholder="Ask a question about your documents…"
          onAsk={setQuestion}
        />
      </div>
      {children}
    </>
  );
}
