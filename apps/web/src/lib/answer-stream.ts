/** Reading the answer stream (see the API's `POST /answers`) and splitting Citations out. */

export type Source = {
  number: number;
  /** The passage, while it exists; null once its Document is deleted. */
  chunk_id?: string | null;
  document_id: string | null;
  document_name: string;
  heading_path: string[];
  page: number | null;
  /** The passage's text as retrieved; sent with every source, so Citations can show it at once. */
  passage?: string;
};

/** A claim removed because its Citations couldn't be checked against their passages. */
export type RemovedClaim = { text: string; reason: string; original: string };

export type AnswerEvent =
  | { event: "start"; conversation_id: string; message_id: string; sources: Source[] }
  | { event: "delta"; text: string }
  | {
      event: "done";
      message_id: string;
      outcome: "answered" | "declined";
      cited: number[];
      /** The answer once its Citations were checked: replaces the streamed text. */
      answer: string;
      verified: boolean;
      removed: RemovedClaim[];
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
 * A Citation marker: `[n]`, or `\u3010n\u3011` (CJK brackets), which models sometimes write
 * instead. The API rewrites saved answers to `[n]`; text still streaming is read either way.
 */
export const CITATION = /[[\u3010](\d{1,2})[\]\u3011]/g;

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
