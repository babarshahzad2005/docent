"use client";

import { useEffect, useRef, useState } from "react";

import { AskBox } from "@/components/ask-box";
import { Button } from "@/components/ui/button";
import { readAnswerEvents, segments, type Source } from "@/lib/answer-stream";

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
  const streaming = turns.some((turn) => turn.status === "streaming");

  const update = (change: (turn: Turn) => Turn) =>
    setTurns((current) => [...current.slice(0, -1), change(current[current.length - 1])]);

  async function ask(question: string) {
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
            window.history.replaceState(null, "", `/conversations/${event.conversation_id}`);
          }
          update((turn) => ({ ...turn, sources: event.sources, messageId: event.message_id }));
        } else if (event.event === "delta") {
          answerSoFar.current += event.text;
          update((turn) => ({ ...turn, answer: turn.answer + event.text }));
        } else if (event.event === "done") {
          // Announced once, when complete, never token by token (DESIGN.md › Accessibility).
          setAnnouncement(answerSoFar.current.replace(/[[【]\d+[\]】]/g, ""));
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
          }));
        }
      }
    } catch {
      update((turn) => ({
        ...turn,
        status: turn.answer ? "interrupted" : "failed",
        error: "The connection dropped. Check your connection and ask again.",
      }));
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
    <div className="mx-auto flex w-full max-w-[40rem] flex-1 flex-col gap-10 px-4 py-8">
      {turns.map((turn, index) => (
        <TurnView key={index} turn={turn} first={index === 0} onRetry={() => void ask(turn.question)} />
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
  );
}

function TurnView({ turn, first, onRetry }: { turn: Turn; first: boolean; onRetry: () => void }) {
  const Heading = first ? "h1" : "h2";
  const available = new Set(turn.sources.map((source) => source.number));
  const cited = turn.sources.filter((source) => turn.cited.includes(source.number));
  const anchor = (n: number) => `source-${turn.messageId ?? "new"}-${n}`;

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
            <a
              key={i}
              href={`#${anchor(part.citation)}`}
              aria-label={`Source ${part.citation}`}
              className="mx-0.5 inline-flex min-w-5 -translate-y-1 items-center justify-center rounded-sm bg-mark px-1 font-sans text-cite font-semibold text-mark-text no-underline"
            >
              {part.citation}
            </a>
          ),
        )}
        {turn.status === "streaming" && turn.answer && (
          <span aria-hidden="true" className="ml-0.5 inline-block h-[1em] w-0.5 translate-y-0.5 bg-foreground" />
        )}
      </div>
      {turn.error && (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-destructive">
          <p>{turn.error}</p>
          <Button variant="outline" size="sm" onClick={onRetry}>
            Ask again
          </Button>
        </div>
      )}
      {cited.length > 0 && (
        <ol aria-label="Sources" className="flex flex-col gap-2 border-t border-border pt-4">
          {cited.map((source) => (
            <li key={source.number} id={anchor(source.number)} className="flex gap-3 text-meta">
              <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-sm bg-mark px-1 text-cite font-semibold text-mark-text">
                {source.number}
              </span>
              <span className="flex flex-col">
                <span className="font-medium text-foreground">{source.document_name}</span>
                <span className="flex flex-wrap gap-x-3 text-muted-foreground">
                  {source.heading_path.length > 0 && <span>{source.heading_path.join(" › ")}</span>}
                  {source.page !== null && <span className="tabular-nums">Page&nbsp;{source.page}</span>}
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
