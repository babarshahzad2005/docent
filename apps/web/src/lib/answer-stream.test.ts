import { describe, expect, it } from "vitest";

import { type AnswerEvent, displayNumbers, readAnswerEvents, segments } from "./answer-stream";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function all(stream: ReadableStream<Uint8Array>): Promise<AnswerEvent[]> {
  const events: AnswerEvent[] = [];
  for await (const event of readAnswerEvents(stream)) events.push(event);
  return events;
}

describe("readAnswerEvents", () => {
  it("reads events even when they arrive split across chunks", async () => {
    const events = await all(
      streamOf(
        'event: start\ndata: {"conversation_id":"c","message_id":"m","sources":[]}\n\nevent: del',
        'ta\ndata: {"text":"Hel',
        'lo [1]"}\n\n',
        'event: done\ndata: {"message_id":"m","outcome":"answered","cited":[1]}\n\n',
      ),
    );

    expect(events.map((e) => e.event)).toEqual(["start", "delta", "done"]);
    expect(events[1]).toEqual({ event: "delta", text: "Hello [1]" });
  });
});

describe("segments", () => {
  it("splits out citations that exist and leaves other brackets as text", () => {
    expect(segments("Ten days [1][2]. See [7] or [x].", new Set([1, 2]))).toEqual([
      { text: "Ten days " },
      { citation: 1 },
      { citation: 2 },
      { text: ". See [7] or [x]." },
    ]);
  });

  it("reads citations written in CJK brackets", () => {
    expect(segments("Fast 【1】.", new Set([1]))).toEqual([
      { text: "Fast " },
      { citation: 1 },
      { text: "." },
    ]);
  });
});

describe("displayNumbers", () => {
  it("numbers sources 1, 2, 3 in the order the answer first cites them, then the rest", () => {
    const shown = displayNumbers("Up to £123 [3], or 80% [1][3]. More [7].", new Set([1, 3, 5, 7]), [5, 1]);

    expect([...shown]).toEqual([
      [3, 1],
      [1, 2],
      [7, 3],
      [5, 4],
    ]);
  });
});
