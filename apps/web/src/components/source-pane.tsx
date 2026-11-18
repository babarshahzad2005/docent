"use client";

import { XIcon } from "lucide-react";
import { type RefObject, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { getPassage, type PassageInContext } from "@/app/passages-actions";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

/** What a Citation itself knows: shown at once, while the text around it loads. */
export type CitedSource = {
  number: number;
  chunk_id: string | null;
  document_name: string;
  heading_path: string[];
  page: number | null;
  passage?: string;
  /** Changes each time it is opened, so opening the same Citation again scrolls to it again. */
  openedAt: number;
};

/** The look of a Citation number (DESIGN.md › Citation number). */
export const CITATION_CHIP =
  "inline-flex min-w-5 items-center justify-center rounded-sm border-b-2 border-mark-edge bg-mark px-1 font-sans text-cite font-semibold text-mark-text";

/** A source's section and page, as shown under its name. */
export function SourceMeta({ headingPath, page }: { headingPath: string[]; page: number | null }) {
  return (
    <span className="flex flex-wrap gap-x-3 text-meta text-muted-foreground">
      {headingPath.length > 0 && <span>{headingPath.join(" › ")}</span>}
      {page !== null && <span className="tabular-nums">Page&nbsp;{page}</span>}
    </span>
  );
}

const WIDE = "(min-width: 1280px)";
const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";
const CLOSE_MS = 200;

/**
 * The cited passage, highlighted in the text around it (DESIGN.md › Layout): a pane beside the
 * answer on wide screens, a sheet over it on narrower ones. Escape or the close button closes
 * it, and focus returns to `returnTo`, the Citation that opened it.
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
  if (wide) return <InlinePane source={source} returnTo={returnTo} onClose={onClose} />;
  return (
    <Sheet open={source !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" finalFocus={returnTo} className="w-full max-w-md gap-0 p-0">
        {source && <SourceBody key={source.openedAt} source={source} inSheet />}
      </SheetContent>
    </Sheet>
  );
}

function InlinePane({
  source,
  returnTo,
  onClose,
}: {
  source: CitedSource | null;
  returnTo: RefObject<HTMLElement | null>;
  onClose: () => void;
}) {
  // Keep showing the last source while the pane closes (200ms, DESIGN.md › Motion).
  const [shown, setShown] = useState(source);
  const [closing, setClosing] = useState(false);
  if (source !== null && source !== shown) {
    setShown(source);
    setClosing(false);
  } else if (source === null && shown !== null && !closing) {
    setClosing(true);
  }

  useEffect(() => {
    if (!closing) return;
    const timer = setTimeout(() => {
      setShown(null);
      setClosing(false);
    }, CLOSE_MS);
    return () => clearTimeout(timer);
  }, [closing]);

  // Escape closes the pane wherever focus is, unless something above it (a dialog) is open.
  useEffect(() => {
    if (source === null) return;
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (document.querySelector('[role="dialog"], [role="alertdialog"]')) return;
      onClose();
      returnTo.current?.focus();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [source, onClose, returnTo]);

  if (shown === null) return null;
  return (
    <aside
      aria-label="Source"
      data-closing={closing || undefined}
      // Opens with opacity 0→1 and a 24px slide over 240ms; closes the same way in 200ms.
      className="sticky top-0 flex h-dvh w-105 shrink-0 flex-col border-l border-border bg-surface transition-[opacity,translate] duration-240 ease-(--ease-out) starting:translate-x-6 starting:opacity-0 data-closing:translate-x-6 data-closing:opacity-0 data-closing:duration-200"
    >
      <SourceBody
        key={shown.openedAt}
        source={shown}
        onClose={() => {
          onClose();
          returnTo.current?.focus();
        }}
      />
    </aside>
  );
}

type Context =
  | { state: "loading" }
  | { state: "loaded"; passage: PassageInContext }
  | { state: "unavailable" } // deleted, or no longer readable by this User
  | { state: "failed"; message: string };

function SourceBody({
  source,
  onClose,
  inSheet = false,
}: {
  source: CitedSource;
  onClose?: () => void;
  inSheet?: boolean;
}) {
  const [context, setContext] = useState<Context>(
    source.chunk_id ? { state: "loading" } : { state: "unavailable" },
  );
  const [marked, setMarked] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const mark = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!source.chunk_id) return;
    let current = true;
    getPassage(source.chunk_id)
      .then((result) => {
        if (!current) return;
        if (!result.ok) setContext({ state: "failed", message: result.message });
        else if (result.value === null) setContext({ state: "unavailable" });
        else setContext({ state: "loaded", passage: result.value });
      })
      .catch(() => current && setContext({ state: "failed", message: CONNECTION }));
    return () => {
      current = false;
    };
  }, [source.chunk_id]);

  // Focus moves into the pane when it opens (the sheet does this itself).
  useEffect(() => {
    if (!inSheet) heading.current?.focus();
  }, [inSheet]);

  // Once the text is in place, scroll to the passage, then fade the highlight in (180ms).
  const ready = context.state !== "loading";
  useEffect(() => {
    if (!ready || !mark.current) return;
    const reduced = window.matchMedia(REDUCED_MOTION).matches;
    mark.current.scrollIntoView?.({ block: "center", behavior: reduced ? "auto" : "smooth" });
    const timer = setTimeout(() => setMarked(true), reduced ? 0 : SCROLL_MS);
    return () => clearTimeout(timer);
  }, [ready]);

  const loaded = context.state === "loaded" ? context.passage : null;
  const passage = loaded?.content ?? source.passage;
  const Title = inSheet ? SheetTitle : "h2";

  return (
    <>
      <header className={`flex items-start gap-3 border-b border-border p-6 ${inSheet ? "pr-14" : ""}`}>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="text-meta text-muted-foreground tabular-nums">Source {source.number}</p>
          <Title
            ref={inSheet ? undefined : heading}
            tabIndex={-1}
            className="font-serif text-heading font-medium text-balance break-words"
          >
            {source.document_name}
          </Title>
          <SourceMeta headingPath={source.heading_path} page={source.page} />
        </div>
        {onClose && (
          <Button variant="ghost" size="icon" aria-label="Close source" onClick={onClose}>
            <XIcon aria-hidden="true" />
          </Button>
        )}
      </header>
      <div className="flex-1 overflow-y-auto p-6">
        {context.state === "unavailable" && (
          <p role="status" className="mb-4 text-meta text-muted-foreground">
            {source.chunk_id
              ? "This source isn’t available any more: its document was removed, or you no longer have access to it."
              : "This document has been removed."}{" "}
            This is the passage as it was when the answer was given.
          </p>
        )}
        {context.state === "failed" && (
          <p role="alert" className="mb-4 text-meta text-destructive">
            {context.message}
          </p>
        )}
        <div className="flex max-w-[34em] flex-col gap-4 font-serif text-source text-pretty">
          {loaded?.before && <p className="text-text-context">{loaded.before}</p>}
          {passage && (
            <p>
              <mark
                ref={mark}
                data-shown={marked || undefined}
                className="rounded-sm border-b-2 border-transparent bg-transparent px-0.5 text-foreground transition-[background-color,border-color] duration-180 ease-(--ease-out) data-shown:border-mark-edge data-shown:bg-mark"
              >
                {passage}
              </mark>
            </p>
          )}
          {!passage && context.state === "loading" && (
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

const CONNECTION = "The source couldn’t be loaded. Check your connection and open it again.";
// Roughly how long a smooth scroll to the passage takes before the highlight appears.
const SCROLL_MS = 300;

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
