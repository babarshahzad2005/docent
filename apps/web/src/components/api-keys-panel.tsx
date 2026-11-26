"use client";

import { type RefObject, useEffect, useId, useRef, useState } from "react";

import {
  type ApiKeySummary,
  createApiKey,
  type NewApiKey,
  revokeApiKey,
} from "@/app/collections-actions";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { formatLocalDate } from "@/lib/dates";
import { useInBrowser } from "@/lib/use-in-browser";

const CONNECTION = "Can’t reach the server. Check your connection and try again.";

/**
 * The Owner's API Keys for a Collection (GLOSSARY: API Key): each can only ask this
 * Collection, works even while it is private, and can be revoked. A new key's secret is shown
 * once: Docent keeps only a hash of it.
 */
export function ApiKeysPanel({
  collectionId,
  initialKeys,
}: {
  collectionId: string;
  initialKeys: ApiKeySummary[];
}) {
  const [keys, setKeys] = useState(initialKeys);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [created, setCreated] = useState<NewApiKey | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const headingId = useId();
  const nameId = useId();
  const problemId = useId();
  const secretHelpId = useId();
  const nameInput = useRef<HTMLInputElement>(null);
  const secretInput = useRef<HTMLInputElement>(null);

  // A new key's secret takes focus: copying it is what to do next.
  useEffect(() => {
    if (created) secretInput.current?.focus();
  }, [created]);

  const copy = async (secret: string) => {
    try {
      await navigator.clipboard.writeText(secret);
      setAnnouncement("API key copied.");
    } catch {
      setAnnouncement("Couldn’t copy. Select the key and copy it yourself.");
    }
  };

  return (
    <section
      aria-labelledby={headingId}
      className="flex w-full flex-col gap-4 self-stretch rounded-lg border border-border bg-surface p-4 text-left"
    >
      <div className="flex flex-col gap-1">
        <h2 id={headingId} className="font-sans text-ui font-semibold">
          API keys
        </h2>
        <p className="text-meta text-pretty text-text-secondary">
          Let your own apps and scripts ask this collection. A key can only ask questions, only of
          this collection, and works even while it’s private. Keep keys secret, and revoke any
          you no longer use.
        </p>
      </div>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!name.trim()) return;
          setCreating(true);
          setProblem(null);
          const result = await createApiKey(collectionId, name).catch(() => null);
          setCreating(false);
          if (!result) return setProblem(CONNECTION);
          if (!result.ok) return setProblem(result.message);
          setKeys((current) => [result.value.key, ...current]);
          setCreated(result.value);
          setName("");
          setAnnouncement(`Key ${result.value.key.name} created. Copy it now: it won’t be shown again.`);
        }}
      >
        <span className="flex min-w-0 flex-1 basis-56 flex-col gap-1">
          <label htmlFor={nameId} className="text-meta text-muted-foreground">
            Key name
          </label>
          <input
            ref={nameInput}
            id={nameId}
            required
            maxLength={80}
            autoComplete="off"
            placeholder="Where it’s used, like Help centre"
            value={name}
            aria-invalid={problem ? true : undefined}
            aria-describedby={problem ? problemId : undefined}
            onChange={(event) => setName(event.target.value)}
            className="h-9 rounded-md border border-border-strong bg-background px-2 text-foreground pointer-coarse:h-11"
          />
        </span>
        <Button type="submit" disabled={creating || !name.trim()}>
          {creating ? "Creating…" : "Create key"}
        </Button>
        {problem && (
          <p id={problemId} role="alert" className="w-full text-meta text-destructive">
            {problem}
          </p>
        )}
      </form>

      {created && (
        <div className="flex flex-col gap-2 rounded-md bg-brand-subtle p-3 text-brand-subtle-text">
          <p id={secretHelpId} className="text-meta">
            Copy this key for {created.key.name} now. Docent doesn’t keep it, so it can’t be shown
            again.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={secretInput}
              readOnly
              aria-label={`API key for ${created.key.name}`}
              aria-describedby={secretHelpId}
              value={created.secret}
              onFocus={(event) => event.currentTarget.select()}
              className="h-9 min-w-0 flex-1 basis-56 rounded-md border border-border-strong bg-background px-2 font-mono text-meta text-foreground"
            />
            <Button size="sm" onClick={() => void copy(created.secret)}>
              Copy key
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setCreated(null);
                nameInput.current?.focus();
              }}
            >
              Done
            </Button>
          </div>
        </div>
      )}

      {keys.length > 0 && (
        <ul className="flex flex-col border-t border-border">
          {keys.map((key) => (
            <KeyRow
              key={key.id}
              apiKey={key}
              afterRevoke={nameInput}
              onRevoked={() => {
                setKeys((current) => current.filter((k) => k.id !== key.id));
                if (created?.key.id === key.id) setCreated(null);
                setAnnouncement(`Key ${key.name} revoked. It no longer works.`);
              }}
            />
          ))}
        </ul>
      )}
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </section>
  );
}

function KeyRow({
  apiKey,
  afterRevoke,
  onRevoked,
}: {
  apiKey: ApiKeySummary;
  /** Where focus goes once the key, and its row, are gone. */
  afterRevoke: RefObject<HTMLElement | null>;
  onRevoked: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [done, setDone] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const inBrowser = useInBrowser();
  // Dates are in the reader's time zone, known only in the browser.
  const date = (iso: string) => (inBrowser ? formatLocalDate(iso) : "…");
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border py-2">
      <span className="flex min-w-0 flex-col">
        <span className="truncate" title={apiKey.name}>
          {apiKey.name}
        </span>
        <span className="text-meta text-muted-foreground">
          Created {date(apiKey.created_at)} ·{" "}
          {apiKey.last_used_at ? `last used ${date(apiKey.last_used_at)}` : "never used"}
        </span>
      </span>
      <AlertDialog
        open={open}
        onOpenChange={(next) => {
          if (revoking) return;
          setOpen(next);
          setProblem(null);
        }}
        // The row goes once the dialog has closed, so the dialog can still send focus on (to
        // the name field); removed sooner, the dialog goes with it and focus falls to the page.
        onOpenChangeComplete={(isOpen) => {
          if (!isOpen && done) onRevoked();
        }}
      >
        <AlertDialogTrigger
          render={<Button variant="ghost" size="sm" aria-label={`Revoke ${apiKey.name}`} />}
        >
          Revoke
        </AlertDialogTrigger>
        <AlertDialogContent finalFocus={done ? afterRevoke : undefined}>
          <AlertDialogTitle>Revoke {apiKey.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            Anything using this key stops getting answers at once. This can’t be undone.
          </AlertDialogDescription>
          {problem && (
            <p role="alert" className="text-destructive">
              {problem}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={revoking}>Cancel</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={revoking}
              onClick={async () => {
                setRevoking(true);
                const result = await revokeApiKey(apiKey.id).catch(() => null);
                setRevoking(false);
                if (!result) return setProblem(CONNECTION);
                if (!result.ok) return setProblem(result.message);
                setDone(true);
                setOpen(false);
              }}
            >
              {revoking ? "Revoking…" : "Revoke key"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  );
}
