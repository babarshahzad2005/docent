"use client";

import { usePathname } from "next/navigation";
import { type ReactNode, useState } from "react";

import { AskBox } from "@/components/ask-box";
import { Conversation } from "@/components/conversation";

/** The Library with a question box above it; asking opens a new Conversation in its place. */
export function LibraryHome({ children }: { children: ReactNode }) {
  const [question, setQuestion] = useState<string | null>(null);
  const pathname = usePathname();

  // Asking moves the address to the new Conversation; coming back to the Library (its link,
  // or Back) shows the Library again. (Adjusted while rendering, as React recommends.)
  const [shownPath, setShownPath] = useState(pathname);
  if (pathname !== shownPath) {
    setShownPath(pathname);
    if (pathname === "/") setQuestion(null);
  }

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
