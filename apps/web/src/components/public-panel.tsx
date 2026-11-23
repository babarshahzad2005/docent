"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState, useSyncExternalStore } from "react";

import { type PublicState, setCollectionPublic } from "@/app/collections-actions";
import { Button } from "@/components/ui/button";
import { formatLocalDate } from "@/lib/dates";

const CONNECTION = "Can’t reach the server. Check your connection and try again.";
const EXPIRIES: { value: string; label: string }[] = [
  { value: "", label: "Never" },
  { value: "1", label: "1 day" },
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
];

/** Where a Public Collection's link leads (FLOWS › Publish). */
export function publicPath(collectionId: string): string {
  return `/public/${collectionId}`;
}

const noChanges = () => () => {};

/** This site's address; empty while rendering on the server, before it is known. */
function useOrigin(): string {
  return useSyncExternalStore(
    noChanges,
    () => window.location.origin,
    () => "",
  );
}

/**
 * The Owner makes a Collection public (GLOSSARY: Public Collection): anyone with the link can
 * ask it without signing in, until the expiry chosen. Turning it off closes the link at once.
 */
export function PublicPanel({
  collectionId,
  initial,
}: {
  collectionId: string;
  initial: PublicState;
}) {
  const router = useRouter();
  const [state, setState] = useState(initial);
  const [expiry, setExpiry] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const headingId = useId();
  const expiryId = useId();
  const problemId = useId();
  const linkInput = useRef<HTMLInputElement>(null);
  const turnOn = useRef<HTMLButtonElement>(null);
  const origin = useOrigin();
  const link = origin + publicPath(collectionId);
  // Dates are shown in the reader's time zone, known only in the browser.
  const until = origin && state.public_until ? formatLocalDate(state.public_until) : null;

  const save = async (makePublic: boolean) => {
    setSaving(true);
    setProblem(null);
    const days = makePublic && expiry ? (Number(expiry) as 1 | 7 | 30) : null;
    const result = await setCollectionPublic(collectionId, makePublic, days).catch(() => null);
    setSaving(false);
    if (!result) return setProblem(CONNECTION);
    if (!result.ok) return setProblem(result.message);
    setState(result.value);
    setAnnouncement(
      result.value.public
        ? "The collection is public. Copy the link to share it."
        : "The collection is private again. Its public link no longer works.",
    );
    router.refresh();
    // Focus follows what to do next: the link to copy, or the way to turn it on again.
    requestAnimationFrame(() =>
      (result.value.public ? linkInput.current : turnOn.current)?.focus(),
    );
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setAnnouncement("Public link copied.");
    } catch {
      setAnnouncement("Couldn’t copy. Select the link and copy it yourself.");
    }
  };

  return (
    <section
      aria-labelledby={headingId}
      className="flex w-full flex-col gap-4 self-stretch rounded-lg border border-border bg-surface p-4 text-left"
    >
      <div className="flex flex-col gap-1">
        <h2 id={headingId} className="font-sans text-ui font-semibold">
          Public link
        </h2>
        <p className="text-meta text-pretty text-text-secondary">
          {state.public
            ? until
              ? `Anyone with the link can ask this collection, without signing in, until ${until}.`
              : "Anyone with the link can ask this collection, without signing in."
            : "Let anyone with the link ask this collection, without signing in. They see answers and the passages cited, not the list of documents, and they can’t change anything. The link is always the same: making it public again reopens it."}
        </p>
      </div>

      {state.public ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={linkInput}
              readOnly
              aria-label="Public link"
              value={link}
              onFocus={(event) => event.currentTarget.select()}
              className="h-9 min-w-0 flex-1 basis-56 rounded-md border border-border-strong bg-background px-2 text-meta text-foreground"
            />
            <Button size="sm" onClick={() => void copy()}>
              Copy link
            </Button>
          </div>
          <div>
            <Button
              variant="outline"
              size="sm"
              disabled={saving}
              aria-describedby={problem ? problemId : undefined}
              onClick={() => void save(false)}
            >
              {saving ? "Saving…" : "Stop sharing publicly"}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-2">
          <span className="flex min-w-0 flex-1 basis-56 flex-col gap-1">
            <label htmlFor={expiryId} className="text-meta text-muted-foreground">
              Stop sharing after
            </label>
            <select
              id={expiryId}
              value={expiry}
              onChange={(event) => setExpiry(event.target.value)}
              className="h-9 w-full min-w-0 rounded-md border border-border-strong bg-background px-2 text-foreground pointer-coarse:h-11"
            >
              {EXPIRIES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </span>
          <Button
            ref={turnOn}
            disabled={saving}
            aria-describedby={problem ? problemId : undefined}
            onClick={() => void save(true)}
          >
            {saving ? "Saving…" : "Make public"}
          </Button>
        </div>
      )}
      {problem && (
        <p id={problemId} role="alert" className="text-meta text-destructive">
          {problem}
        </p>
      )}
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
    </section>
  );
}
