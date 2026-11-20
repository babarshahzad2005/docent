"use client";

import { CheckIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";
import { Fragment, type ReactNode, useEffect, useId, useRef, useState } from "react";

import { AskBox } from "@/components/ask-box";
import {
  type CollectionChoice,
  defaultScope,
  ScopeChips,
  scopeNames,
} from "@/components/scope-chips";
import { CITATION_CHIP, type CitedSource, SourceMeta, SourcePane } from "@/components/source-pane";
import { Button } from "@/components/ui/button";
import {
  type ConflictVersion,
  normalizeCitations,
  type Outcome,
  readAnswerEvents,
  type RemovedClaim,
  segments,
  type Source,
  withoutCitations,
} from "@/lib/answer-stream";

export type Turn = {
  question: string;
  answer: string;
  sources: Source[];
  cited: number[];
  status: "streaming" | "complete" | "declined" | "interrupted" | "failed";
  messageId?: string;
  error?: string;
  /** The Collections it was answered from. */
  scope?: string[];
  /** How it ended, once finished; a Decline's `cited` are its closest passages. */
  outcome?: Outcome;
  /** The Citations were checked against their passages (ADR 0007). */
  verified?: boolean;
  removed?: RemovedClaim[];
  /** When the answer's Documents disagree: each version, newest first. */
  conflict?: ConflictVersion[] | null;
  /** Removed sentences fading out of the streamed text, before the checked answer replaces it. */
  fading?: string[];
};

// DESIGN.md › Motion: an unsupported claim fades out over 150ms, then the line updates.
const FADE_MS = 150;

/**
 * A Conversation: each question with its streamed answer, Citations, and the sources they
 * point to, then a box for the next question. Starts by asking `startQuestion` if given.
 */
export function Conversation({
  conversationId: initialId,
  initialTurns,
  startQuestion,
  scope: initialScope,
  collections = [],
}: {
  conversationId: string | null;
  initialTurns: Turn[];
  startQuestion?: string;
  /** The Collections to answer from; follow-ups keep it unless the User changes it. */
  scope?: string[];
  /** The User's Collections, to choose the Scope from and name it. */
  collections?: CollectionChoice[];
}) {
  const [scope, setScope] = useState(() => usableScope(initialScope, collections));
  const [turns, setTurns] = useState(initialTurns);
  const [announcement, setAnnouncement] = useState("");
  const conversationId = useRef(initialId);
  const started = useRef(false);
  const answerSoFar = useRef("");
  const [openSource, setOpenSource] = useState<CitedSource | null>(null);
  const openedBy = useRef<HTMLElement | null>(null);
  const streaming = turns.some((turn) => turn.status === "streaming");

  const update = (change: (turn: Turn) => Turn) =>
    setTurns((current) => [...current.slice(0, -1), change(current[current.length - 1])]);

  const asking = useRef(false);

  async function ask(question: string) {
    // One answer at a time: a second stream would write into the same turn.
    if (asking.current) return;
    asking.current = true;
    setTurns((current) => [
      ...current,
      { question, answer: "", sources: [], cited: [], status: "streaming", scope },
    ]);
    setAnnouncement("");
    answerSoFar.current = "";
    try {
      const response = await fetch("/api/answers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, conversation_id: conversationId.current, scope }),
      });
      if (!response.ok || !response.body) {
        const detail = await response.json().catch(() => null);
        update((turn) => ({
          ...turn,
          status: "failed",
          error: detail?.detail ?? "Docent couldn’t answer right now. Try again in a minute.",
        }));
        return;
      }
      for await (const event of readAnswerEvents(response.body)) {
        if (event.event === "start") {
          if (conversationId.current === null) {
            conversationId.current = event.conversation_id;
            // The Conversation now exists: give it its own address without reloading.
            // (Pushed, so Back returns to the Library.)
            window.history.pushState(null, "", `/conversations/${event.conversation_id}`);
          }
          update((turn) => ({
            ...turn,
            sources: event.sources,
            messageId: event.message_id,
            scope: event.scope ?? turn.scope,
          }));
        } else if (event.event === "delta") {
          answerSoFar.current += event.text;
          update((turn) => ({ ...turn, answer: turn.answer + event.text }));
        } else if (event.event === "done") {
          // Announced once, when complete, never token by token (DESIGN.md › Accessibility),
          // with what verification removed.
          const final = event.answer || answerSoFar.current;
          setAnnouncement(
            [withoutCitations(final), event.verified ? removedSummary(event.removed) : ""]
              .filter(Boolean)
              .join(" "),
          );
          const fading = event.removed.map((claim) => claim.original);
          const checked = (turn: Turn): Turn => ({
            ...turn,
            answer: event.answer || turn.answer,
            status: event.outcome === "answered" ? "complete" : "declined",
            cited: event.cited,
            outcome: event.outcome,
            verified: event.verified,
            removed: event.removed,
            conflict: event.conflict ?? null,
            fading: undefined,
          });
          if (fading.length === 0) {
            update(checked);
          } else {
            // The streamed text, with its markers written as the API writes them, so the
            // removed sentences can be found in it and faded out.
            update((turn) => ({ ...turn, answer: normalizeCitations(turn.answer), fading }));
            await new Promise((resolve) => setTimeout(resolve, FADE_MS));
            update(checked);
          }
        } else {
          update((turn) => ({
            ...turn,
            status: event.partial ? "interrupted" : "failed",
            error: event.message,
            cited: event.cited,
          }));
        }
      }
      // A stream that ended without done or error was cut off on the way.
      update((turn) =>
        turn.status !== "streaming"
          ? turn
          : {
              ...turn,
              status: turn.answer ? "interrupted" : "failed",
              error: "The answer was cut off. Ask again to get the whole answer.",
            },
      );
    } catch {
      update((turn) => ({
        ...turn,
        status: turn.answer ? "interrupted" : "failed",
        error: "The connection dropped. Check your connection and ask again.",
      }));
    } finally {
      asking.current = false;
    }
  }

  useEffect(() => {
    if (startQuestion && !started.current) {
      started.current = true;
      void ask(startQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ask once, on arrival
  }, []);

  return (
    <div className="flex flex-1">
      <div className="mx-auto flex w-full max-w-[40rem] min-w-0 flex-1 flex-col gap-10 px-4 py-8">
        {turns.map((turn, index) => (
          <TurnView
            key={index}
            turn={turn}
            first={index === 0}
            canRetry={!streaming}
            collections={collections}
            onRetry={() => void ask(turn.question)}
            onOpenSource={(source, opener) => {
              openedBy.current = opener;
              setOpenSource(source);
            }}
          />
        ))}
        <p aria-live="polite" className="sr-only">
          {announcement}
        </p>
        <div className="sticky bottom-4 mt-auto flex flex-col gap-2 bg-background pt-2">
          <ScopeChips collections={collections} value={scope} onChange={setScope} />
          <AskBox
            label="Ask a follow-up question"
            placeholder="Ask a follow-up…"
            disabled={streaming}
            onAsk={(question) => void ask(question)}
          />
        </div>
      </div>
      <SourcePane source={openSource} returnTo={openedBy} onClose={() => setOpenSource(null)} />
    </div>
  );
}

function TurnView({
  turn,
  first,
  canRetry,
  collections,
  onRetry,
  onOpenSource,
}: {
  turn: Turn;
  first: boolean;
  canRetry: boolean;
  collections: CollectionChoice[];
  onRetry: () => void;
  onOpenSource: (source: CitedSource, opener: HTMLElement) => void;
}) {
  const Heading = first ? "h1" : "h2";
  const asked = turn.scope ? scopeNames(turn.scope, collections) : null;
  const closestId = useId();
  const available = new Set(turn.sources.map((source) => source.number));
  const cited = turn.sources.filter((source) => turn.cited.includes(source.number));
  const byNumber = new Map(turn.sources.map((source) => [source.number, source]));
  // DESIGN.md: the accessible name says which source, not just the number.
  const label = (n: number) => {
    const source = byNumber.get(n);
    if (!source) return `Source ${n}`;
    return [`Source ${n}`, source.document_name, source.page !== null ? `page ${source.page}` : null]
      .filter(Boolean)
      .join(", ");
  };
  const open = (n: number) => (event: React.MouseEvent<HTMLElement>) => {
    const source = byNumber.get(n);
    if (source) {
      onOpenSource(
        { ...source, chunk_id: source.chunk_id ?? null, openedAt: Date.now() },
        event.currentTarget,
      );
    }
  };

  const chip = (n: number) =>
    byNumber.has(n) ? (
      <button
        type="button"
        aria-label={label(n)}
        onClick={open(n)}
        className={`${CITATION_CHIP} cursor-pointer`}
      >
        {n}
      </button>
    ) : null;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <Heading className="font-serif text-question font-medium text-balance">{turn.question}</Heading>
        {asked && <p className="text-meta text-muted-foreground">Asked of {asked}</p>}
      </div>
      <div
        className="font-serif text-answer whitespace-pre-wrap text-pretty"
        aria-busy={turn.status === "streaming"}
      >
        {turn.status === "streaming" && !turn.answer && (
          <span className="font-sans text-ui text-muted-foreground">Finding passages…</span>
        )}
        {withFading(turn.answer, turn.fading ?? []).map((piece, p) => {
          const parts = segments(piece.text, available).map((part, i) =>
            "text" in part ? (
              <span key={i}>{part.text}</span>
            ) : (
              <button
                key={i}
                type="button"
                aria-label={label(part.citation)}
                onClick={open(part.citation)}
                className={`${CITATION_CHIP} mx-0.5 -translate-y-1 cursor-pointer`}
              >
                {part.citation}
              </button>
            ),
          );
          return piece.fading ? (
            <span
              key={`fading-${p}`}
              data-fading
              className="opacity-0 transition-opacity duration-150 ease-(--ease-out) starting:opacity-100"
            >
              {parts}
            </span>
          ) : (
            <Fragment key={p}>{parts}</Fragment>
          );
        })}
        {turn.status === "streaming" && turn.answer && (
          <span aria-hidden="true" className="ml-0.5 inline-block h-[1em] w-0.5 translate-y-0.5 bg-foreground" />
        )}
      </div>
      {turn.outcome === "no_documents" && (
        <p>
          <Link
            href="/"
            className="text-brand underline underline-offset-2 [@media(hover:hover)_and_(pointer:fine)]:hover:text-brand-strong"
          >
            Go to your library to upload documents
          </Link>
        </p>
      )}
      {turn.conflict && turn.conflict.length > 1 && turn.status !== "streaming" && (
        <ConflictNotice
          versions={turn.conflict}
          chip={(n) => chip(n)}
          level={first ? "h2" : "h3"}
        />
      )}
      {turn.verified && turn.status !== "streaming" && (
        <VerificationLine
          checked={citationCount(turn.answer, available)}
          removed={turn.removed ?? []}
        />
      )}
      {turn.error && (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-destructive">
          <p>{turn.error}</p>
          <Button variant="outline" size="sm" disabled={!canRetry} onClick={onRetry}>
            Ask again
          </Button>
        </div>
      )}
      {cited.length > 0 && turn.outcome === "declined" && (
        // DESIGN.md › Writing: a Decline is followed by the closest passages.
        <p id={closestId} className="text-meta text-text-secondary">
          The closest passages in your documents:
        </p>
      )}
      {cited.length > 0 && (
        <ol
          aria-label={turn.outcome === "declined" ? undefined : "Sources"}
          aria-labelledby={turn.outcome === "declined" ? closestId : undefined}
          className="flex flex-col gap-1 border-t border-border pt-4"
        >
          {cited.map((source) => (
            <li key={source.number}>
              <button
                type="button"
                onClick={open(source.number)}
                className="flex w-full cursor-pointer gap-3 rounded-lg px-2 py-2 text-left text-meta hover:bg-muted"
              >
                <span className={`${CITATION_CHIP} h-5`}>{source.number}</span>
                <span className="flex flex-col">
                  <span className="font-medium text-foreground">{source.document_name}</span>
                  <SourceMeta headingPath={source.heading_path} page={source.page} />
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** The answer's text with the sentences being removed marked, so they can fade out. */
function withFading(answer: string, fading: string[]): { text: string; fading: boolean }[] {
  let pieces = [{ text: answer, fading: false }];
  for (const sentence of fading) {
    pieces = pieces.flatMap((piece) => {
      const at = piece.fading ? -1 : piece.text.indexOf(sentence);
      if (at === -1) return [piece];
      return [
        { text: piece.text.slice(0, at), fading: false },
        { text: sentence, fading: true },
        { text: piece.text.slice(at + sentence.length), fading: false },
      ].filter((p) => p.text);
    });
  }
  return pieces;
}

/** The Citations left in a checked answer (each one verified), counting repeats. */
function citationCount(answer: string, available: Set<number>): number {
  return segments(answer, available).filter((part) => "citation" in part).length;
}

/** "1 claim was removed because it couldn’t be checked." */
function removedSummary(removed: RemovedClaim[]): string {
  if (removed.length === 0) return "";
  return removed.length === 1
    ? "1 claim was removed because it couldn’t be checked."
    : `${removed.length} claims were removed because they couldn’t be checked.`;
}

/**
 * DESIGN.md › Answer: a check mark and "All N citations checked against their source"; if
 * claims were removed, how many, and what they were and why. With nothing checked there is
 * no check mark: the answer itself says it couldn't be checked.
 */
function VerificationLine({ checked, removed }: { checked: number; removed: RemovedClaim[] }) {
  if (checked === 0 && removed.length === 0) return null;
  const summary =
    checked === 0
      ? ""
      : checked === 1
        ? removed.length === 0
          ? "The citation was checked against its source."
          : "1 citation was checked against its source."
        : removed.length === 0
          ? `All ${checked} citations checked against their source.`
          : `${checked} citations were checked against their source.`;
  return (
    <div className="flex flex-col gap-1 text-meta text-text-secondary">
      <p className="flex items-center gap-1.5">
        {checked > 0 && <CheckIcon aria-hidden="true" className="size-4 shrink-0 text-brand" />}
        {[summary, removedSummary(removed)].filter(Boolean).join(" ")}
      </p>
      {removed.length > 0 && (
        <details className={checked > 0 ? "pl-5.5" : undefined}>
          <summary className="cursor-pointer text-brand underline-offset-2 [@media(hover:hover)_and_(pointer:fine)]:hover:underline">
            What was removed
          </summary>
          <ul className="mt-1 flex flex-col gap-1">
            {removed.map((claim, i) => (
              <li key={i}>
                <span className="text-foreground">“{claim.text}”</span>: {claim.reason}.
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/**
 * The Scope to start from: the one given, less any Collection the User can no longer ask;
 * if nothing is left, all of their own Collections (never an empty Scope).
 */
function usableScope(scope: string[] | undefined, collections: CollectionChoice[]): string[] {
  const ids = new Set(collections.map((collection) => collection.id));
  const usable = (scope ?? []).filter((id) => ids.has(id));
  return usable.length > 0 ? usable : defaultScope(collections);
}

/**
 * DESIGN.md › Conflict notice: a bordered surface with an icon, the heading "Your documents
 * disagree", and a table of each value, its document, and its Effective Date, newest first.
 * The answer follows the newest.
 */
function ConflictNotice({
  versions,
  chip,
  level,
}: {
  versions: ConflictVersion[];
  chip: (n: number) => ReactNode;
  /** One below the question's heading. */
  level: "h2" | "h3";
}) {
  const headingId = useId();
  const Heading = level;
  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-3 rounded-lg border border-border-strong bg-surface p-4"
    >
      <Heading id={headingId} className="flex items-center gap-2 font-sans text-ui font-semibold">
        <TriangleAlertIcon aria-hidden="true" className="size-4 shrink-0 text-warning-icon" />
        Your documents disagree
      </Heading>
      <p className="text-meta text-text-secondary">
        The answer follows the newest. Each version, newest first:
      </p>
      <table className="w-full text-left text-meta">
        <thead className="text-muted-foreground">
          <tr>
            <th scope="col" className="pb-1 pr-3 font-medium">What it says</th>
            <th scope="col" className="pb-1 pr-3 font-medium">Document</th>
            <th scope="col" className="pb-1 font-medium">Effective</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((version) => (
            <tr key={version.number} className="border-t border-border align-top">
              <td className="py-2 pr-3">
                <span className="flex items-start gap-2">
                  {chip(version.number)}
                  <span>“{version.value}”</span>
                </span>
              </td>
              <td className="py-2 pr-3 break-words">{version.document_name}</td>
              <td className="py-2 tabular-nums whitespace-nowrap">
                {version.effective_date ? formatDate(version.effective_date) : "Not set"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** A date as people write it: "1 January 2024". */
function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}
