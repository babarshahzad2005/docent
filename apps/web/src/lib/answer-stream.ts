/** Reading the answer stream (see the API's `POST /answers`) and splitting Citations out. */

export type Source = {
  number: number;
  /** The passage, while it exists; null once its Document is deleted. */
  chunk_id?: string | null;
  document_id: string | null;
  document_name: string;
  heading_path: string[];
  page: number | null;
  /**
   * The passage's text as retrieved; sent with every source, so Citations can show it at once.
   * Null in a saved Conversation once the User has lost access to it.
   */
  passage?: string | null;
  /** The User can no longer read its Collection (PRD decision log: the text is hidden). */
  access_lost?: boolean;
};

/**
 * How a finished answer ended. "declined": the Documents don't contain the answer;
 * "unverified": nothing in it could be checked, so it isn't shown; "no_documents": there was
 * nothing in Scope to search.
 */
export type Outcome = "answered" | "declined" | "unverified" | "no_documents";

/** One Document's side when Documents disagree (#48). */
export type ConflictVersion = {
  number: number;
  value: string;
  document_name: string;
  effective_date: string | null;
};

/** A claim removed because its Citations couldn't be checked against their passages. */
export type RemovedClaim = { text: string; reason: string; original: string };

export type AnswerEvent =
  | {
      event: "start";
      conversation_id: string;
      message_id: string;
      sources: Source[];
      /** The Collections it is answered from, as recorded (only those the User can read). */
      scope?: string[];
    }
  | { event: "delta"; text: string }
  | {
      event: "done";
      message_id: string;
      outcome: Outcome;
      /** The passages the answer cites; for a Decline, the closest passages. */
      cited: number[];
      /** The answer once its Citations were checked: replaces the streamed text. */
      answer: string;
      verified: boolean;
      removed: RemovedClaim[];
      /** When the answer's Documents disagree: each version, newest first. */
      conflict?: ConflictVersion[] | null;
    }
  | { event: "error"; message: string; partial: boolean; cited: number[] };

/** Parses server-sent events from a byte stream, yielding each as it completes. */
export async function* readAnswerEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<AnswerEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      let end = buffer.indexOf("\n\n");
      while (end !== -1) {
        const parsed = parseEvent(buffer.slice(0, end));
        if (parsed) yield parsed;
        buffer = buffer.slice(end + 2);
        end = buffer.indexOf("\n\n");
      }
      if (done) return;
    }
  } finally {
    reader.releaseLock();
  }
}

function parseEvent(block: string): AnswerEvent | null {
  let name = "";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (!name || data.length === 0) return null;
  return { event: name, ...JSON.parse(data.join("\n")) } as AnswerEvent;
}

export type Segment = { text: string } | { citation: number };

/**
 * A Citation marker: `[n]`, or `\u3010n\u3011` (CJK brackets, sometimes with a line range:
 * `\u30101\u2020L1-L4\u3011`), which models sometimes write instead. The API rewrites saved
 * answers to `[n]`; text still streaming is read either way.
 */
export const CITATION = /[[\u3010](\d{1,2})(?:\u2020[^\]\u3011\n]{0,20})?[\]\u3011]/g;

/** Every Citation marker written as `[n]`, as the API saves them. */
export function normalizeCitations(answer: string): string {
  return answer.replace(CITATION, "[$1]");
}

/** The answer's words without its Citation markers, for reading aloud. */
export function withoutCitations(answer: string): string {
  return answer.replace(CITATION, "");
}

/** An answer's text with its `[n]` markers split out, keeping only numbers that exist. */
export function segments(answer: string, available: Set<number>): Segment[] {
  const parts: Segment[] = [];
  let last = 0;
  for (const match of answer.matchAll(CITATION)) {
    const number = Number(match[1]);
    if (!available.has(number)) continue;
    if (match.index > last) parts.push({ text: answer.slice(last, match.index) });
    parts.push({ citation: number });
    last = match.index + match[0].length;
  }
  if (last < answer.length) parts.push({ text: answer.slice(last) });
  return parts;
}

/**
 * The number each source is shown with: 1, 2, 3… in the order the answer first cites them,
 * then any others (`rest`) in their own order. The model numbers the passages it was given,
 * so an answer citing [1] and [3] would otherwise show a gap. Stable while streaming, since
 * markers only ever add to the end.
 */
export function displayNumbers(
  answer: string,
  available: Set<number>,
  rest: number[] = [],
): Map<number, number> {
  const shown = new Map<number, number>();
  const cited = segments(answer, available).flatMap((part) =>
    "citation" in part ? [part.citation] : [],
  );
  for (const n of [...cited, ...rest]) {
    if (!shown.has(n)) shown.set(n, shown.size + 1);
  }
  return shown;
}
