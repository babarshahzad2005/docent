"use client";

import { XIcon } from "lucide-react";
import { type RefObject, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { getPassage, type PassageInContext } from "@/app/passages-actions";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";

/** What the Citation itself knows, shown at once while the passage's context loads. */
export type CitedSource = {
  number: number;
  chunk_id: string | null;
  document_name: string;
  heading_path: string[];
  page: number | null;
  passage?: string;
};

const WIDE = "(min-width: 1280px)";

/**
 * The cited passage, highlighted in the text around it (DESIGN.md › Layout): a pane beside the
 * answer on wide screens, a sheet over it on narrower ones. Closing returns focus to `returnTo`,
 * the Citation that opened it.
 */
export function SourcePane({
  source,
  returnTo,
  onClose,
}: {
  source: CitedSource | null;
  returnTo: RefObject<HTMLElement | null>;
  onClose: () => void;
}) {
  const wide = useMediaQuery(WIDE);

  if (wide) {
    if (!source) return null;
    return (
      <aside
        aria-label="Source"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            onClose();
            returnTo.current?.focus();
          }
        }}
        // Opening: opacity 0→1 and 24px slide, 240ms --ease-out (DESIGN.md › Motion).
        className="sticky top-0 flex h-dvh w-105 shrink-0 flex-col border-l border-border bg-surface transition-[opacity,translate] duration-240 ease-(--ease-out) starting:translate-x-6 starting:opacity-0"
      >
        <SourceBody
          key={`${source.chunk_id}-${source.number}`}
          source={source}
          onClose={() => {
            onClose();
            returnTo.current?.focus();
          }}
        />
      </aside>
    );
  }
  return (
    <Sheet open={source !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" finalFocus={returnTo} className="w-full max-w-md gap-0 p-0">
        {source && (
          <SourceBody key={`${source.chunk_id}-${source.number}`} source={source} inSheet />
        )}
      </SheetContent>
    </Sheet>
  );
}

function SourceBody({
  source,
  onClose,
  inSheet = false,
}: {
  source: CitedSource;
  onClose?: () => void;
  inSheet?: boolean;
}) {
  const [context, setContext] = useState<PassageInContext | null | "loading" | "error">(
    source.chunk_id ? "loading" : null,
  );
  const heading = useRef<HTMLHeadingElement>(null);
  const mark = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!source.chunk_id) return;
    let current = true;
    getPassage(source.chunk_id)
      .then((result) => current && setContext(result.ok ? result.value : "error"))
      .catch(() => current && setContext("error"));
    return () => {
      current = false;
    };
  }, [source.chunk_id]);

  // Focus moves into the pane when it opens (the sheet does this itself).
  useEffect(() => {
    if (!inSheet) heading.current?.focus();
  }, [inSheet]);

  // Bring the highlighted passage into view once its context has arrived.
  const ready = context !== "loading";
  useEffect(() => {
    if (ready) mark.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [ready]);

  const loaded = typeof context === "object" && context !== null ? context : null;
  const removed = !source.chunk_id || context === null;
  const passage = loaded?.content ?? source.passage;
  const Title = inSheet ? SheetTitle : "h2";

  return (
    <>
      <header className="flex items-start gap-3 border-b border-border p-6">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="text-meta text-muted-foreground tabular-nums">Source {source.number}</p>
          <Title
            ref={inSheet ? undefined : heading}
            tabIndex={-1}
            className="font-serif text-heading font-medium text-balance break-words outline-none"
          >
            {source.document_name}
          </Title>
          <p className="flex flex-wrap gap-x-3 text-meta text-muted-foreground">
            {source.heading_path.length > 0 && <span>{source.heading_path.join(" › ")}</span>}
            {source.page !== null && <span className="tabular-nums">Page&nbsp;{source.page}</span>}
          </p>
        </div>
        {onClose && (
          <Button variant="ghost" size="icon" aria-label="Close source" onClick={onClose}>
            <XIcon aria-hidden="true" />
          </Button>
        )}
      </header>
      <div className="flex-1 overflow-y-auto p-6">
        {removed && (
          <p role="status" className="mb-4 text-meta text-muted-foreground">
            This document has been removed. This is the passage as it was when the answer was
            given.
          </p>
        )}
        {context === "error" && (
          <p role="alert" className="mb-4 text-meta text-destructive">
            The text around this passage couldn’t be loaded. Close the source and open it again.
          </p>
        )}
        <div className="flex max-w-[34em] flex-col gap-4 font-serif text-source text-pretty">
          {loaded?.before && <p className="text-text-context">{loaded.before}</p>}
          {passage ? (
            <p>
              <mark
                ref={mark}
                className="rounded-sm border-b-2 border-mark-edge bg-mark px-0.5 text-foreground transition-opacity duration-180 ease-(--ease-out) starting:opacity-0"
              >
                {passage}
              </mark>
            </p>
          ) : (
            <p role="status" className="font-sans text-ui text-muted-foreground">
              Loading the passage…
            </p>
          )}
          {loaded?.after && <p className="text-text-context">{loaded.after}</p>}
        </div>
      </div>
    </>
  );
}

function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (change) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", change);
      return () => list.removeEventListener("change", change);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
