"use client";

import { usePathname } from "next/navigation";
import { type ReactNode, useState } from "react";

import { AskBox } from "@/components/ask-box";
import { Conversation } from "@/components/conversation";
import { type CollectionChoice, ScopeChips } from "@/components/scope-chips";

/**
 * A page with a question box above it; asking opens a new Conversation in its place,
 * answered from the Collections chosen as its Scope (`defaultScope` to start with).
 */
export function LibraryHome({
  collections,
  defaultScope,
  label,
  children,
}: {
  collections: CollectionChoice[];
  defaultScope: string[];
  label: string;
  children: ReactNode;
}) {
  const [question, setQuestion] = useState<string | null>(null);
  const [scope, setScope] = useState(defaultScope);
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
        scope={scope}
        collections={collections}
      />
    );
  }
  return (
    <>
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 pt-8 sm:px-6">
        <ScopeChips collections={collections} value={scope} onChange={setScope} />
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
