"use client";

import { useEffect, useRef, useState } from "react";

import { AskBox } from "@/components/ask-box";
import { CITATION_CHIP, type CitedSource, SourceMeta, SourcePane } from "@/components/source-pane";
import { Button } from "@/components/ui/button";
import {
  readAnswerEvents,
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
};

/**
 * A Conversation: each question with its streamed answer, Citations, and the sources they
 * point to, then a box for the next question. Starts by asking `startQuestion` if given.
 */
export function Conversation({
  conversationId: initialId,
  initialTurns,
  startQuestion,
}: {
  conversationId: string | null;
  initialTurns: Turn[];
  startQuestion?: string;
}) {
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
      { question, answer: "", sources: [], cited: [], status: "streaming" },
    ]);
    setAnnouncement("");
    answerSoFar.current = "";
    try {
      const response = await fetch("/api/answers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, conversation_id: conversationId.current }),
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
          update((turn) => ({ ...turn, sources: event.sources, messageId: event.message_id }));
        } else if (event.event === "delta") {
          answerSoFar.current += event.text;
          update((turn) => ({ ...turn, answer: turn.answer + event.text }));
        } else if (event.event === "done") {
          // Announced once, when complete, never token by token (DESIGN.md › Accessibility).
          setAnnouncement(withoutCitations(answerSoFar.current));
          update((turn) => ({
            ...turn,
            status: event.outcome === "declined" ? "declined" : "complete",
            cited: event.cited,
          }));
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
        <div className="sticky bottom-4 mt-auto">
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
  onRetry,
  onOpenSource,
}: {
  turn: Turn;
  first: boolean;
  canRetry: boolean;
  onRetry: () => void;
  onOpenSource: (source: CitedSource, opener: HTMLElement) => void;
}) {
  const Heading = first ? "h1" : "h2";
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

  return (
    <section className="flex flex-col gap-4">
      <Heading className="font-serif text-question font-medium text-balance">{turn.question}</Heading>
      <div
        className="font-serif text-answer whitespace-pre-wrap text-pretty"
        aria-busy={turn.status === "streaming"}
      >
        {turn.status === "streaming" && !turn.answer && (
          <span className="font-sans text-ui text-muted-foreground">Finding passages…</span>
        )}
        {segments(turn.answer, available).map((part, i) =>
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
        )}
        {turn.status === "streaming" && turn.answer && (
          <span aria-hidden="true" className="ml-0.5 inline-block h-[1em] w-0.5 translate-y-0.5 bg-foreground" />
        )}
      </div>
      {turn.error && (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-destructive">
          <p>{turn.error}</p>
          <Button variant="outline" size="sm" disabled={!canRetry} onClick={onRetry}>
            Ask again
          </Button>
        </div>
      )}
      {cited.length > 0 && (
        <ol aria-label="Sources" className="flex flex-col gap-1 border-t border-border pt-4">
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
