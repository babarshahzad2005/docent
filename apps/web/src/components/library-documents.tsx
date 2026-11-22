"use client";

import Link from "next/link";
import { CheckIcon, CircleAlertIcon, UploadIcon } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { formatDate } from "@/lib/dates";

import {
  deleteDocument,
  type DocumentSummary,
  finishUpload,
  listDocuments,
  retryDocument,
  setEffectiveDate,
  startUpload,
} from "@/app/documents-actions";
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
import { createClient } from "@/lib/supabase/client";
import { precheck, sha256 } from "@/lib/upload-checks";

const ACCEPT = [
  ".pdf",
  ".docx",
  ".md",
  ".markdown",
  ".txt",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/markdown",
  "text/plain",
].join(",");
const POLL_MS = 2000;
const PARALLEL_UPLOADS = 3;

type Status = DocumentSummary["status"];

/** A new version's progress, as part of a sentence. */
const REPLACEMENT_PROGRESS: Record<Status, string> = {
  uploading: "uploading",
  queued: "waiting to be processed",
  parsing: "being read",
  embedding: "being indexed",
  indexed: "ready",
  failed: "failed",
};

const STATUS_LABELS: Record<Status, string> = {
  uploading: "Uploading…",
  queued: "Waiting…",
  parsing: "Reading…",
  embedding: "Indexing…",
  indexed: "Ready",
  failed: "Failed",
};

/** Statuses the server is still working through, so the Library keeps refreshing. */
const isProcessing = (status: Status) =>
  status === "queued" || status === "parsing" || status === "embedding";
const isSettled = (status: Status) =>
  status === "indexed" || status === "failed";

/** The Documents in the Library, with uploading and live status. */
export function LibraryDocuments({
  collection,
  initialDocuments,
  demoHref,
  settings,
}: {
  collection: {
    id: string;
    name: string;
    role: "owner" | "editor" | "viewer";
    is_demo: boolean;
    is_personal: boolean;
  };
  initialDocuments: DocumentSummary[];
  /** Where the Demo Collection is, offered while this Library is empty. */
  demoHref?: string;
  /** The Owner's controls for the Collection itself (Rename, Delete), beside its name. */
  settings?: ReactNode;
}) {
  const personal = collection.is_personal;
  const [documents, setDocuments] = useState(() =>
    onlyIn(collection.id, initialDocuments),
  );
  // When each Document's Effective Date was last saved here (see the poll below).
  const datesSaved = useRef(new Map<string, number>());
  // Bumped to restart status refreshing after it stopped on an error.
  const [refreshes, setRefreshes] = useState(0);
  const canEdit = collection.role !== "viewer";
  const [errors, setErrors] = useState<string[]>([]);
  // Files are being dragged over the Library: show where to drop them.
  const [dragging, setDragging] = useState(false);
  // Files the Collection already has: the User chooses to keep both or skip.
  const [duplicates, setDuplicates] = useState<
    { file: File; message: string; replaceable?: DocumentSummary }[]
  >([]);
  const [announcement, setAnnouncement] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const previous = useRef(
    new Map(initialDocuments.map((d) => [d.id, d.status])),
  );
  const wasEmpty = useRef(initialDocuments.length === 0);
  // Each Document's replacement status as last seen, to announce when one finishes or fails.
  const replacements = useRef(
    new Map(
      initialDocuments.flatMap((d) =>
        d.replacement ? [[d.id, { status: d.replacement.status }] as const] : [],
      ),
    ),
  );
  // Documents this page is uploading right now (their status is still "uploading").
  const [sending, setSending] = useState<Set<string>>(new Set());
  const busy = useRef(0);
  const uploadRef = useRef<(files: File[]) => void>(() => undefined);

  const processing = documents.some(
    (d) =>
      isProcessing(d.status) ||
      (d.replacement !== null &&
        d.replacement !== undefined &&
        isProcessing(d.replacement.status)),
  );

  // Refresh statuses while anything is processing: one request at a time, stopping on errors.
  useEffect(() => {
    if (!processing) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const asked = Date.now();
        const result = await listDocuments();
        if (stopped) return;
        if (!result.ok) {
          setErrors([`Progress stopped updating: ${result.message}`]);
          return;
        }
        // A date saved while this poll was on its way is newer than what it brings back.
        setDocuments((current) =>
          onlyIn(collection.id, result.value).map((fresh) => {
            const saved = datesSaved.current.get(fresh.id);
            const mine = current.find((d) => d.id === fresh.id);
            return saved !== undefined && saved > asked && mine
              ? { ...fresh, effective_date: mine.effective_date }
              : fresh;
          }),
        );
      } catch {
        if (!stopped)
          setErrors([
            "Progress stopped updating. Reload the page to check again.",
          ]);
        return;
      }
      timer = setTimeout(poll, POLL_MS);
    };
    timer = setTimeout(poll, POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [processing, refreshes, collection.id]);

  // Announce Documents that just finished, once, for screen readers.
  useEffect(() => {
    const finished = documents.filter(
      (d) => isSettled(d.status) && previous.current.get(d.id) !== d.status,
    );
    previous.current = new Map(documents.map((d) => [d.id, d.status]));
    // A replacement finishing (it disappears from its Document) or failing.
    const replaced: string[] = [];
    for (const d of documents) {
      const before = replacements.current.get(d.id);
      const now = d.replacement;
      if (before && before.status !== "failed" && !now)
        replaced.push(`${d.name} has been replaced.`);
      else if (before && before.status !== "failed" && now?.status === "failed")
        replaced.push(`${now.name} couldn’t replace ${d.name}.`);
    }
    replacements.current = new Map(
      documents.flatMap((d) =>
        d.replacement ? [[d.id, { status: d.replacement.status }] as const] : [],
      ),
    );
    const messages = [
      ...finished.map((d) =>
        d.status === "indexed" ? `${d.name} is ready.` : `${d.name} failed.`,
      ),
      ...replaced,
    ];
    if (messages.length > 0) setAnnouncement(messages.join(" "));
  }, [documents]);

  // The first upload swaps the empty state for the list; keep focus on the upload button.
  useEffect(() => {
    if (wasEmpty.current && documents.length > 0) {
      wasEmpty.current = false;
      button.current?.focus();
    }
  }, [documents.length]);

  // The whole window takes dropped files, so a drop that misses the list never makes the
  // browser open the file instead (which would also cut off uploads in progress).
  useEffect(() => {
    if (!canEdit) return;
    let depth = 0; // dragenter/dragleave fire for every element crossed; count to know when out
    const enter = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth += 1;
      setDragging(true);
    };
    const leave = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };
    const over = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    };
    const drop = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setDragging(false);
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length > 0) uploadRef.current(files);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, [canEdit]);

  async function upload(files: File[]) {
    // A new batch clears old messages only when nothing is still uploading; otherwise an
    // earlier batch's refusals and duplicate questions would vanish unanswered.
    if (busy.current === 0) {
      setErrors([]);
      setDuplicates([]);
    }
    // A few files at a time: each one's transfer to storage is the slow part.
    const queue = [...files];
    const sendNext = async () => {
      for (let file = queue.shift(); file; file = queue.shift())
        await uploadOne(file, {});
    };
    await Promise.all(
      Array.from(
        { length: Math.min(PARALLEL_UPLOADS, queue.length) },
        sendNext,
      ),
    );
  }

  uploadRef.current = (files) => void upload(files);

  type Send = {
    /** Keep both when the Collection already has a Document with this content or name. */
    allowDuplicate?: boolean;
    /** Send the file as a new version of this Document (GLOSSARY: Replace). */
    replaces?: DocumentSummary;
  };

  async function uploadOne(file: File, options: Send) {
    busy.current += 1;
    try {
      await sendOne(file, options);
    } finally {
      busy.current -= 1;
    }
  }

  async function sendOne(
    file: File,
    { allowDuplicate = false, replaces }: Send,
  ) {
    const fail = (message: string) =>
      setErrors((current) => [...current, message]);
    const refused = precheck(file);
    if (refused) {
      fail(refused);
      return;
    }
    // A file named like a Document already here is probably its new version: ask.
    const namesake = documents.find((d) => d.name === file.name && d.status !== "failed");
    if (!replaces && !allowDuplicate && namesake) {
      // Replace is offered when the Document can take a new version now.
      const replaceable =
        namesake.status === "indexed" &&
        (!namesake.replacement || namesake.replacement.status === "failed")
          ? namesake
          : undefined;
      const message = replaceable
        ? `${file.name} is already in this collection. Replace it with this file, or keep both?`
        : `${file.name} is already in this collection. Upload it anyway to keep both.`;
      setDuplicates((current) => [...current, { file, message, replaceable }]);
      setAnnouncement(message);
      return;
    }
    const replacing = (change: (d: DocumentSummary) => DocumentSummary) =>
      setDocuments((current) =>
        current.map((d) => (d.id === replaces?.id ? change(d) : d)),
      );
    const supabase = createClient();
    let sentId: string | null = null;
    try {
      const started = await startUpload(
        collection.id,
        file.name,
        file.size,
        await sha256(file),
        allowDuplicate,
        replaces?.id,
      );
      if (!started.ok) {
        if (started.duplicate) {
          setDuplicates((current) => [
            ...current,
            { file, message: started.message },
          ]);
          setAnnouncement(started.message);
        } else {
          fail(started.message);
        }
        return;
      }
      const { document, upload: target } = started.value;
      const asReplacement = (status: DocumentSummary["status"]) => ({
        id: document.id,
        name: document.name,
        status,
        failure_reason: null,
        can_retry: false,
      });
      if (replaces) {
        // The new version shows on the Document it replaces, which keeps answering.
        replacing((d) => ({ ...d, replacement: asReplacement("uploading") }));
      } else {
        setDocuments((current) => [document, ...current]);
      }
      sentId = document.id;
      setSending((current) => new Set(current).add(document.id));
      const { error } = await supabase.storage
        .from(target.bucket)
        .uploadToSignedUrl(target.path, target.token, file, {
          contentType: file.type || "application/octet-stream",
        });
      if (error) {
        // Cancel the half-made Document, so it neither counts nor blocks uploading again.
        if (replaces) replacing((d) => ({ ...d, replacement: null }));
        else
          setDocuments((current) =>
            current.filter((d) => d.id !== document.id),
          );
        void deleteDocument(document.id).catch(() => undefined);
        fail(
          `${file.name} couldn't be uploaded (${error.message}). Upload it again.`,
        );
        return;
      }
      const finished = await finishUpload(document.id);
      if (!finished.ok) {
        fail(finished.message);
        return;
      }
      if (replaces) {
        replacing((d) => ({
          ...d,
          replacement: asReplacement(finished.value.status),
        }));
        setAnnouncement(
          `${replaces.name} is being replaced by ${file.name}. Answers use ${replaces.name} as it is until then.`,
        );
      } else {
        setDocuments((current) =>
          current.map((d) => (d.id === document.id ? finished.value : d)),
        );
      }
    } catch {
      fail(
        `${file.name} couldn't be uploaded. Check your connection and upload it again.`,
      );
    } finally {
      if (sentId !== null) {
        const id = sentId;
        setSending((current) => {
          const next = new Set(current);
          next.delete(id);
          return next;
        });
      }
    }
  }

  const picker = (
    <>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          if (files.length > 0) void upload(files);
        }}
      />
      <Button ref={button} size="lg" onClick={() => input.current?.click()}>
        <UploadIcon aria-hidden="true" />
        Upload documents
      </Button>
    </>
  );

  const messages = (
    <>
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
      {duplicates.length > 0 && (
        <ul
          aria-label="Already in this collection"
          className="flex flex-col gap-3"
        >
          {duplicates.map(({ file, message, replaceable }) => {
            // The choice's own buttons disappear with it; continue from the upload button.
            const settle = () => {
              setDuplicates((current) =>
                current.filter((d) => d.file !== file),
              );
              button.current?.focus();
            };
            return (
              <li
                key={`${file.name}-${file.lastModified}-${file.size}`}
                className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3"
              >
                <p>{message}</p>
                <div className="flex flex-wrap gap-2">
                  {replaceable && (
                    <Button
                      size="sm"
                      onClick={() => {
                        settle();
                        void uploadOne(file, { replaces: replaceable });
                      }}
                    >
                      Replace with this file
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant={replaceable ? "outline" : "default"}
                    onClick={() => {
                      settle();
                      void uploadOne(file, { allowDuplicate: true });
                    }}
                  >
                    {replaceable ? "Keep both" : "Upload anyway"}
                  </Button>
                  <Button variant="outline" size="sm" onClick={settle}>
                    Skip
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {errors.length > 0 && (
        <ul role="alert" className="flex flex-col gap-1 text-destructive">
          {errors.map((message, index) => (
            <li key={index}>{message}</li>
          ))}
        </ul>
      )}
    </>
  );

  const dropHint = dragging && (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-3 z-40 flex items-center justify-center rounded-xl border-2 border-dashed border-brand bg-brand-subtle/90 px-6 text-center text-brand-subtle-text"
    >
      Drop files to add them to your {collection.name} collection
    </div>
  );

  // Real work only: Documents the server is processing, and ones this page is still sending.
  // An upload abandoned elsewhere stays "uploading" until the server gives up on it.
  const remaining = documents.filter(
    (d) =>
      isProcessing(d.status) || (d.status === "uploading" && sending.has(d.id)),
  ).length;
  const progress = remaining > 0 && (
    <p className="text-muted-foreground tabular-nums">
      {remaining} {remaining === 1 ? "document" : "documents"} indexing…
    </p>
  );

  if (!canEdit) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
        <div className="flex flex-col gap-2">
          <h1 className="font-serif text-question font-medium">
            {collection.name}
          </h1>
          {collection.is_demo ? (
            <p className="text-muted-foreground text-pretty">
              Openly licensed workplace guidance from GOV.UK and the GitLab
              Handbook, for trying Docent. Questions asked on this page are
              answered from these documents only. Each one links to where it was
              published, with its licence.
            </p>
          ) : (
            <p className="text-muted-foreground">
              You can ask about these documents.
            </p>
          )}
        </div>
        {progress}
        {documents.length === 0 && (
          <p className="text-muted-foreground">
            There are no documents here yet. Your own documents are in your
            Personal Library.
          </p>
        )}
        <ul
          aria-label="Documents"
          className="flex flex-col border-t border-border"
        >
          {documents.map((document) => (
            <DocumentRow
              key={document.id}
              document={document}
              canRetry={false}
              canDelete={false}
              afterDelete={button}
              onDelete={async () => null}
              onRetry={async () => false}
              canDate={false}
              onDate={async () => null}
              canReplace={false}
              onReplace={() => undefined}
              onCancelReplacement={async () => undefined}
              onRetryReplacement={async () => undefined}
            />
          ))}
        </ul>
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="relative mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-4 px-4 py-12 text-center">
        {dropHint}
        <h1 className="font-serif text-question font-medium text-balance">
          {personal ? "Your library is empty" : `${collection.name} is empty`}
        </h1>
        <p className="text-muted-foreground text-pretty">
          Docent answers questions only from documents you add. Upload PDFs,
          Word documents, Markdown, or plain text to{" "}
          {personal ? `your ${collection.name} collection` : "this collection"}{" "}
          to get started. You can choose several at once, or drop them here.
        </p>
        <div className="mt-2">{picker}</div>
        {settings}
        {demoHref && (
          <p className="text-muted-foreground text-pretty">
            Or try Docent first with the{" "}
            <Link
              href={demoHref}
              className="text-brand underline underline-offset-2 [@media(hover:hover)_and_(pointer:fine)]:hover:text-brand-strong"
            >
              Demo Collection
            </Link>
            : openly licensed workplace guidance you can ask about now.
          </p>
        )}
        {messages}
      </div>
    );
  }

  return (
    <div className="relative mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      {dropHint}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="font-serif text-question font-medium">
            {personal ? "Library" : collection.name}
          </h1>
          <p className="text-muted-foreground">
            {personal
              ? `Documents in your ${collection.name} collection`
              : "Documents in this collection"}
          </p>
          {settings && <div className="-ml-2">{settings}</div>}
        </div>
        {picker}
      </div>
      {messages}
      {progress}
      <ul
        aria-label="Documents"
        className="flex flex-col border-t border-border"
      >
        {documents.map((document) => (
          <DocumentRow
            key={document.id}
            document={document}
            canRetry={canEdit && document.can_retry}
            // A file this page is still sending can't be deleted yet; it finishes in moments.
            // One left "uploading" elsewhere (a closed tab) can.
            canDelete={canEdit && !sending.has(document.id)}
            afterDelete={button}
            onDelete={async () => {
              try {
                const deleted = await deleteDocument(document.id);
                if (!deleted.ok) return deleted.message;
                setAnnouncement(`${document.name} was deleted.`);
                setDocuments((current) =>
                  current.filter((d) => d.id !== document.id),
                );
                return null;
              } catch {
                return `${document.name} couldn't be deleted. Check your connection and try again.`;
              }
            }}
            canDate={canEdit && !sending.has(document.id)}
            canReplace={
              canEdit &&
              document.status === "indexed" &&
              (!document.replacement ||
                document.replacement.status === "failed")
            }
            onReplace={(file) => void uploadOne(file, { replaces: document })}
            onCancelReplacement={async () => {
              const replacement = document.replacement;
              if (!replacement) return;
              const cancelled = await deleteDocument(replacement.id).catch(
                () => null,
              );
              if (!cancelled?.ok) {
                setErrors([
                  `The failed replacement of ${document.name} couldn't be dismissed. Try again.`,
                ]);
                return;
              }
              setDocuments((current) =>
                current.map((d) =>
                  d.id === document.id ? { ...d, replacement: null } : d,
                ),
              );
              setAnnouncement(
                `The failed replacement of ${document.name} was dismissed.`,
              );
            }}
            onRetryReplacement={async () => {
              const replacement = document.replacement;
              if (!replacement) return;
              const retried = await retryDocument(replacement.id).catch(
                () => null,
              );
              if (!retried?.ok) {
                setErrors([
                  retried?.message ??
                    `${document.name}'s replacement couldn't be retried.`,
                ]);
                return;
              }
              setDocuments((current) =>
                current.map((d) =>
                  d.id === document.id && d.replacement
                    ? {
                        ...d,
                        replacement: {
                          ...d.replacement,
                          status: retried.value.status,
                          failure_reason: null,
                          can_retry: false,
                        },
                      }
                    : d,
                ),
              );
              setRefreshes((n) => n + 1);
            }}
            onDate={async (date) => {
              try {
                const changed = await setEffectiveDate(document.id, date);
                if (!changed.ok) return changed.message;
                datesSaved.current.set(document.id, Date.now());
                setDocuments((current) =>
                  current.map((d) =>
                    d.id === document.id ? changed.value : d,
                  ),
                );
                setAnnouncement(
                  `${document.name} now applies from ${formatDate(changed.value.effective_date)}.`,
                );
                return null;
              } catch {
                return "The date couldn’t be saved. Check your connection and try again.";
              }
            }}
            onRetry={async () => {
              try {
                const retried = await retryDocument(document.id);
                if (!retried.ok) {
                  setErrors([retried.message]);
                  return false;
                }
                setErrors([]);
                setAnnouncement(`${document.name} is being processed again.`);
                setDocuments((current) =>
                  current.map((d) =>
                    d.id === document.id ? retried.value : d,
                  ),
                );
                setRefreshes((n) => n + 1);
                return true;
              } catch {
                setErrors([
                  `${document.name} couldn't be retried. Check your connection.`,
                ]);
                return false;
              }
            }}
          />
        ))}
      </ul>
    </div>
  );
}

function DocumentRow({
  document,
  canRetry,
  canDelete,
  afterDelete,
  onRetry,
  onDelete,
  canDate,
  onDate,
  canReplace,
  onReplace,
  onCancelReplacement,
  onRetryReplacement,
}: {
  document: DocumentSummary;
  canRetry: boolean;
  canDelete: boolean;
  /** Whether the User may change the Effective Date. */
  canDate: boolean;
  /** Resolves to null once saved, or to a message saying why it wasn't. */
  onDate: (date: string) => Promise<string | null>;
  /** Whether the User may give the Document new content (GLOSSARY: Replace). */
  canReplace: boolean;
  onReplace: (file: File) => void;
  onCancelReplacement: () => Promise<void>;
  onRetryReplacement: () => Promise<void>;
  /** Where focus goes once the Document (and so its row) is gone. */
  afterDelete: React.RefObject<HTMLButtonElement | null>;
  /** Resolves to whether the Document was queued again. */
  onRetry: () => Promise<boolean>;
  /** Resolves to null once deleted, or to a message saying why it wasn't. */
  onDelete: () => Promise<string | null>;
}) {
  const failed = document.status === "failed";
  const [retrying, setRetrying] = useState(false);
  const row = useRef<HTMLLIElement>(null);
  const tone = failed
    ? "text-destructive"
    : document.status === "indexed"
      ? "text-brand"
      : "text-muted-foreground";
  return (
    <li
      ref={row}
      tabIndex={-1}
      aria-label={document.name}
      className="flex flex-col gap-1 border-b border-border py-3"
    >
      <div className="flex items-baseline justify-between gap-4">
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-medium" title={document.name}>
            {document.name}
          </span>
          {document.source_url && (
            <span className="flex flex-wrap gap-x-3 text-meta">
              {document.source_credit && (
                <span className="w-full text-muted-foreground">{document.source_credit}</span>
              )}
              <a
                href={document.source_url}
                rel="noreferrer"
                target="_blank"
                className="text-brand underline underline-offset-2 [@media(hover:hover)_and_(pointer:fine)]:hover:text-brand-strong"
              >
                Source{" "}
                <span className="sr-only">of {document.name} (opens in a new tab)</span>
              </a>
              {document.source_licence_url && (
                <a
                  href={document.source_licence_url}
                  rel="noreferrer license"
                  target="_blank"
                  className="text-brand underline underline-offset-2 [@media(hover:hover)_and_(pointer:fine)]:hover:text-brand-strong"
                >
                  Licence{" "}
                  <span className="sr-only">of {document.name} (opens in a new tab)</span>
                </a>
              )}
            </span>
          )}
        </span>
        <span
          className={`flex shrink-0 items-center gap-1 text-meta tabular-nums transition-colors duration-150 ${tone}`}
        >
          {document.status === "indexed" && (
            <CheckIcon aria-hidden="true" className="size-4" />
          )}
          {failed && <CircleAlertIcon aria-hidden="true" className="size-4" />}
          {STATUS_LABELS[document.status]}
        </span>
      </div>
      <div className="flex items-center justify-between gap-4">
        {/* A failed file has been removed (it counts as 0 bytes), so neither applies. */}
        {failed ? (
          <span />
        ) : (
          <span className="flex flex-wrap items-center gap-x-3 text-meta text-muted-foreground tabular-nums">
            <span>{formatSize(document.size_bytes)}</span>
            <EffectiveDate
              name={document.name}
              date={document.effective_date}
              canChange={canDate}
              onChange={onDate}
            />
          </span>
        )}
        <span className="flex items-center gap-1">
          {canReplace && (
            <ReplaceDocument
              name={document.name}
              onFile={(file) => {
                onReplace(file);
                requestAnimationFrame(() => row.current?.focus());
              }}
            />
          )}
          {canDelete && (
            <DeleteDocument
              name={document.name}
              afterDelete={afterDelete}
              onDelete={onDelete}
            />
          )}
        </span>
      </div>
      {document.replacement && (
        <Replacement
          name={document.name}
          replacement={document.replacement}
          canChange={canDelete}
          onSettled={() => row.current?.focus()}
          onCancel={onCancelReplacement}
          onRetry={onRetryReplacement}
        />
      )}
      {failed && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {document.failure_reason && (
            <p className="text-meta text-destructive">
              {document.failure_reason}
            </p>
          )}
          {canRetry && (
            <Button
              variant="outline"
              size="sm"
              aria-label={`Retry ${document.name}`}
              disabled={retrying}
              onClick={async () => {
                setRetrying(true);
                const queued = await onRetry();
                setRetrying(false);
                // The button disappears once the Document is queued; keep focus on its row.
                if (queued) row.current?.focus();
              }}
            >
              {retrying ? "Retrying…" : "Retry"}
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

/** Replace: choose the file with the Document's new content. */
function ReplaceDocument({
  name,
  onFile,
}: {
  name: string;
  onFile: (file: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) onFile(file);
        }}
      />
      <Button
        variant="ghost"
        size="sm"
        aria-label={`Replace ${name}`}
        onClick={() => input.current?.click()}
      >
        Replace
      </Button>
    </>
  );
}

/** The new version on its way: its progress, or why it failed and what to do. */
function Replacement({
  name,
  replacement,
  canChange,
  onSettled,
  onCancel,
  onRetry,
}: {
  name: string;
  replacement: NonNullable<DocumentSummary["replacement"]>;
  canChange: boolean;
  /** Its buttons go once used: focus moves to the Document's row. */
  onSettled: () => void;
  onCancel: () => Promise<void>;
  onRetry: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const run = (action: () => Promise<void>) => async () => {
    setBusy(true);
    await action();
    setBusy(false);
    onSettled();
  };
  if (replacement.status !== "failed") {
    return (
      <p className="text-meta text-muted-foreground">
        Replacing with {replacement.name}:{" "}
        {REPLACEMENT_PROGRESS[replacement.status]}. Until then, answers use {name} as it is.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-meta text-destructive">
        {replacement.name} couldn’t replace {name}
        {replacement.failure_reason
          ? `: ${replacement.failure_reason}`
          : "."}{" "}
        {name} still answers as it is.
      </p>
      {canChange && (
        <span className="flex gap-2">
          {replacement.can_retry && (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={run(onRetry)}
              aria-label={`Retry replacing ${name}`}
            >
              Retry
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={run(onCancel)}
            aria-label={`Dismiss the failed replacement of ${name}`}
          >
            Dismiss
          </Button>
        </span>
      )}
    </div>
  );
}

/** "Effective 1 January 2024", and for Owners and Editors a way to change it. */
function EffectiveDate({
  name,
  date,
  canChange,
  onChange,
}: {
  name: string;
  date: string;
  canChange: boolean;
  onChange: (date: string) => Promise<string | null>;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(date);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const change = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const inputId = useId();

  useEffect(() => {
    if (editing) input.current?.focus();
  }, [editing]);

  const close = () => {
    setEditing(false);
    setProblem(null);
    // Focus returns to the button that opened the form, once it is back.
    requestAnimationFrame(() => change.current?.focus());
  };

  if (!editing) {
    return (
      <span className="flex items-center gap-1">
        Effective {formatDate(date)}
        {canChange && (
          <Button
            ref={change}
            variant="ghost"
            size="sm"
            aria-label={`Change the effective date of ${name}`}
            onClick={() => {
              setValue(date);
              setProblem(null);
              setEditing(true);
            }}
          >
            Change
          </Button>
        )}
      </span>
    );
  }
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!value) return;
        setSaving(true);
        const message = await onChange(value);
        setSaving(false);
        if (message) setProblem(message);
        else close();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !saving) {
          event.preventDefault();
          close();
        }
      }}
    >
      <label htmlFor={inputId}>Effective from</label>
      <input
        ref={input}
        id={inputId}
        type="date"
        required
        min="1900-01-01"
        max="2100-12-31"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        className="h-8 rounded-md border border-border-strong bg-surface px-2 text-foreground pointer-coarse:h-11"
      />
      <Button type="submit" size="sm" disabled={saving || !value}>
        {saving ? "Saving…" : "Save"}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={saving}
        onClick={close}
      >
        Cancel
      </Button>
      {problem && (
        <p role="alert" className="w-full text-destructive">
          {problem}
        </p>
      )}
    </form>
  );
}


/** Delete, after a confirmation that names the Document. */
function DeleteDocument({
  name,
  afterDelete,
  onDelete,
}: {
  name: string;
  afterDelete: React.RefObject<HTMLButtonElement | null>;
  onDelete: () => Promise<string | null>;
}) {
  const [open, setOpen] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (deleting) return;
        setOpen(next);
        setProblem(null);
      }}
    >
      <AlertDialogTrigger
        render={
          <Button variant="ghost" size="sm" aria-label={`Delete ${name}`} />
        }
      >
        Delete
      </AlertDialogTrigger>
      {/* On cancel focus returns to the Delete button; once deleted, that button is gone. */}
      <AlertDialogContent finalFocus={deleted ? afterDelete : undefined}>
        <AlertDialogTitle>Delete {name}?</AlertDialogTitle>
        <AlertDialogDescription>
          The document and everything Docent made from it are removed. This
          can’t be undone.
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
              setDeleting(false);
              if (failure) {
                setProblem(failure);
              } else {
                setDeleted(true);
                setOpen(false);
              }
            }}
          >
            {deleting ? "Deleting…" : "Delete"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function carriesFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

/** The API lists every Collection's Documents; a Library view shows one Collection's. */
function onlyIn(
  collectionId: string,
  documents: DocumentSummary[],
): DocumentSummary[] {
  return documents.filter(
    (document) => document.collection_id === collectionId,
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
