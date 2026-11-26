"use client";

import { PlusIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import {
  type ApiKeySummary,
  createCollection,
  deleteCollection,
  type InviteSummary,
  type MemberSummary,
  renameCollection,
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
import { ApiKeysPanel } from "@/components/api-keys-panel";
import { MembersList } from "@/components/members-list";
import { PublicPanel } from "@/components/public-panel";
import { SharePanel } from "@/components/share-panel";
import { Button } from "@/components/ui/button";

const CONNECTION =
  "Can’t reach the server. Check your connection and try again.";

/** "New collection" in the Library navigation: name it, and it opens, empty. */
export function NewCollection() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);

  if (!open) {
    return (
      <button
        ref={opener}
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-text-secondary pointer-coarse:min-h-11 [@media(hover:hover)_and_(pointer:fine)]:hover:bg-muted"
      >
        <PlusIcon aria-hidden="true" className="size-4" />
        New collection
      </button>
    );
  }
  return (
    <NameForm
      label="Collection name"
      initial=""
      submit="Create"
      busy="Creating…"
      onSave={async (name) => {
        const created = await createCollection(name).catch(() => null);
        if (!created) return CONNECTION;
        if (!created.ok) return created.message;
        router.push(`/collections/${created.value.id}`);
        router.refresh();
        setOpen(false);
        return null;
      }}
      onCancel={() => {
        setOpen(false);
        requestAnimationFrame(() => opener.current?.focus());
      }}
      stacked
    />
  );
}

/** The Owner's Share, API keys, Rename, and Delete for a Collection they created. */
export function CollectionSettings({
  collection,
  documentCount,
  invites,
  members,
  apiKeys,
}: {
  collection: { id: string; name: string; public?: boolean; public_until?: string | null };
  /** How many Documents deleting it removes, said in the confirmation. */
  documentCount: number;
  /** Invites still waiting, shown when sharing opens. */
  invites: InviteSummary[];
  /** Everyone with access, shown when sharing opens. */
  members: MemberSummary[];
  /** The Collection's API Keys, shown when "API keys" opens. */
  apiKeys: ApiKeySummary[];
}) {
  const router = useRouter();
  const [renaming, setRenaming] = useState(false);
  // Opens at once when invites are waiting, or it is public, so the Owner sees that.
  const [sharing, setSharing] = useState(invites.length > 0 || Boolean(collection.public));
  const panelId = useId();
  const [keysOpen, setKeysOpen] = useState(false);
  const keysPanelId = useId();
  const rename = useRef<HTMLButtonElement>(null);

  if (renaming) {
    return (
      <NameForm
        label="New name"
        initial={collection.name}
        submit="Save"
        busy="Saving…"
        onSave={async (name) => {
          const renamed = await renameCollection(collection.id, name).catch(
            () => null,
          );
          if (!renamed) return CONNECTION;
          if (!renamed.ok) return renamed.message;
          setRenaming(false);
          router.refresh();
          requestAnimationFrame(() => rename.current?.focus());
          return null;
        }}
        onCancel={() => {
          setRenaming(false);
          requestAnimationFrame(() => rename.current?.focus());
        }}
      />
    );
  }
  return (
    <div className="flex w-full flex-col gap-3">
      <div data-settings-row className="flex flex-wrap items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={sharing}
          aria-controls={panelId}
          onClick={() => setSharing((open) => !open)}
        >
          Share
        </Button>
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={keysOpen}
          aria-controls={keysPanelId}
          onClick={() => setKeysOpen((open) => !open)}
        >
          API keys
        </Button>
        <Button
          ref={rename}
          variant="ghost"
          size="sm"
          aria-label={`Rename ${collection.name}`}
          onClick={() => setRenaming(true)}
        >
          Rename
        </Button>
        <DeleteCollection
          name={collection.name}
          documentCount={documentCount}
          onDelete={async () => {
            const deleted = await deleteCollection(collection.id).catch(
              () => null,
            );
            if (!deleted) return CONNECTION;
            if (!deleted.ok) return deleted.message;
            router.push("/");
            router.refresh();
            return null;
          }}
        />
      </div>
      {/* Hidden, not unmounted, when closed: its invites survive closing and opening it. */}
      <div id={panelId} hidden={!sharing}>
        <div className="flex flex-col gap-4">
          <SharePanel collectionId={collection.id} initialInvites={invites} />
          <PublicPanel
            collectionId={collection.id}
            initial={{
              public: collection.public ?? false,
              public_until: collection.public_until ?? null,
            }}
          />
          {members.length > 0 && (
            <div className="rounded-lg border border-border bg-surface p-4">
              <MembersList
                // Starts again from the server's list when it changes (someone accepted).
                key={members.map((m) => `${m.user_id}:${m.role}`).join()}
                collection={collection}
                initialMembers={members}
                isOwner
              />
            </div>
          )}
        </div>
      </div>
      <div id={keysPanelId} hidden={!keysOpen}>
        <ApiKeysPanel collectionId={collection.id} initialKeys={apiKeys} />
      </div>
    </div>
  );
}

function DeleteCollection({
  name,
  documentCount,
  onDelete,
}: {
  name: string;
  documentCount: number;
  onDelete: () => Promise<string | null>;
}) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const what =
    documentCount === 0
      ? "It has no documents."
      : documentCount === 1
        ? "Its 1 document, and everything Docent made from it, are deleted too."
        : `Its ${documentCount} documents, and everything Docent made from them, are deleted too.`;
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (deleting) return;
        setOpen(next);
        setProblem(null);
      }}
    >
      <AlertDialogTrigger render={<Button variant="ghost" size="sm" />}>
        Delete collection
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogTitle>Delete {name}?</AlertDialogTitle>
        <AlertDialogDescription>
          {what} Anyone you shared it with loses access. This can’t be undone.
        </AlertDialogDescription>
        {problem && (
          <p role="alert" className="text-destructive">
            {problem}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
          <Button
            variant="destructive"
            disabled={deleting}
            onClick={async () => {
              setDeleting(true);
              const failure = await onDelete();
              if (failure) {
                setDeleting(false);
                setProblem(failure);
              }
              // On success the page moves to the Library; the dialog goes with it.
            }}
          >
            {deleting ? "Deleting…" : "Delete collection"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** A one-field form for a Collection's name; Escape cancels. */
function NameForm({
  label,
  initial,
  submit,
  busy,
  onSave,
  onCancel,
  stacked = false,
}: {
  label: string;
  initial: string;
  submit: string;
  busy: string;
  /** Resolves to null once saved, or to a message saying why it wasn't. */
  onSave: (name: string) => Promise<string | null>;
  onCancel: () => void;
  /** Field above the buttons, for the narrow navigation. */
  stacked?: boolean;
}) {
  const [value, setValue] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const problemId = useId();

  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);

  return (
    <form
      className={
        stacked
          ? "flex flex-col gap-2 px-2"
          : "flex flex-wrap items-center gap-2"
      }
      onSubmit={async (event) => {
        event.preventDefault();
        if (!value.trim()) return;
        setSaving(true);
        const message = await onSave(value);
        setSaving(false);
        setProblem(message);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !saving) {
          event.preventDefault();
          onCancel();
        }
      }}
    >
      <label
        htmlFor={inputId}
        className={stacked ? "text-meta text-muted-foreground" : "sr-only"}
      >
        {label}
      </label>
      <input
        ref={input}
        id={inputId}
        required
        maxLength={120}
        value={value}
        aria-invalid={problem ? true : undefined}
        aria-describedby={problem ? problemId : undefined}
        onChange={(event) => setValue(event.target.value)}
        className="h-8 min-w-0 rounded-md border border-border-strong bg-surface px-2 text-foreground pointer-coarse:h-11"
      />
      <span className="flex gap-2">
        <Button type="submit" size="sm" disabled={saving || !value.trim()}>
          {saving ? busy : submit}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={saving}
          onClick={onCancel}
        >
          Cancel
        </Button>
      </span>
      {problem && (
        <p
          id={problemId}
          role="alert"
          className="w-full text-meta text-destructive"
        >
          {problem}
        </p>
      )}
    </form>
  );
}
