"use client";

import { CheckIcon, UploadIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  type DocumentSummary,
  finishUpload,
  listDocuments,
  resumeProcessing,
  startUpload,
} from "@/app/documents-actions";
import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";

const ACCEPT = ".md,.markdown,.txt,text/markdown,text/plain";
const POLL_MS = 2000;
// While Documents are processing, nudge the server this often in case a batch paused.
const RESUME_EVERY_POLLS = 30;

type Status = DocumentSummary["status"];

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
const isSettled = (status: Status) => status === "indexed" || status === "failed";

/** The Documents in the Library, with uploading and live status. */
export function LibraryDocuments({
  collection,
  initialDocuments,
}: {
  collection: { id: string; name: string };
  initialDocuments: DocumentSummary[];
}) {
  const [documents, setDocuments] = useState(initialDocuments);
  const [errors, setErrors] = useState<string[]>([]);
  const [announcement, setAnnouncement] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const previous = useRef(new Map(initialDocuments.map((d) => [d.id, d.status])));
  const wasEmpty = useRef(initialDocuments.length === 0);

  const processing = documents.some((d) => isProcessing(d.status));

  // Refresh statuses while anything is processing: one request at a time, stopping on errors.
  useEffect(() => {
    if (!processing) return;
    let stopped = false;
    let polls = 0;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      polls += 1;
      try {
        if (polls % RESUME_EVERY_POLLS === 0) await resumeProcessing();
        const result = await listDocuments();
        if (stopped) return;
        if (!result.ok) {
          setErrors([`Progress stopped updating: ${result.message}`]);
          return;
        }
        setDocuments(result.value);
      } catch {
        if (!stopped) setErrors(["Progress stopped updating. Reload the page to check again."]);
        return;
      }
      timer = setTimeout(poll, POLL_MS);
    };
    timer = setTimeout(poll, POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [processing]);

  // Announce Documents that just finished, once, for screen readers.
  useEffect(() => {
    const finished = documents.filter(
      (d) => isSettled(d.status) && previous.current.get(d.id) !== d.status,
    );
    previous.current = new Map(documents.map((d) => [d.id, d.status]));
    if (finished.length > 0) {
      setAnnouncement(
        finished
          .map((d) => (d.status === "indexed" ? `${d.name} is ready.` : `${d.name} failed.`))
          .join(" "),
      );
    }
  }, [documents]);

  // The first upload swaps the empty state for the list; keep focus on the upload button.
  useEffect(() => {
    if (wasEmpty.current && documents.length > 0) {
      wasEmpty.current = false;
      button.current?.focus();
    }
  }, [documents.length]);

  async function upload(files: File[]) {
    setErrors([]);
    const fail = (message: string) => setErrors((current) => [...current, message]);
    const supabase = createClient();
    for (const file of files) {
      try {
        const started = await startUpload(collection.id, file.name, file.size);
        if (!started.ok) {
          fail(started.message);
          continue;
        }
        const { document, upload: target } = started.value;
        setDocuments((current) => [document, ...current]);
        const { error } = await supabase.storage
          .from(target.bucket)
          .uploadToSignedUrl(target.path, target.token, file, {
            contentType: file.type || "text/plain",
          });
        if (error) {
          // The server marks the unfinished Document as failed later; hide it here.
          setDocuments((current) => current.filter((d) => d.id !== document.id));
          fail(`${file.name} couldn't be uploaded (${error.message}). Upload it again.`);
          continue;
        }
        const finished = await finishUpload(document.id);
        if (!finished.ok) {
          fail(finished.message);
          continue;
        }
        setDocuments((current) =>
          current.map((d) => (d.id === document.id ? finished.value : d)),
        );
      } catch {
        fail(`${file.name} couldn't be uploaded. Check your connection and upload it again.`);
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
      {errors.length > 0 && (
        <ul role="alert" className="flex flex-col gap-1 text-destructive">
          {errors.map((message, index) => (
            <li key={index}>{message}</li>
          ))}
        </ul>
      )}
    </>
  );

  if (documents.length === 0) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-4 px-4 py-12 text-center">
        <h1 className="font-serif text-question font-medium text-balance">Your library is empty</h1>
        <p className="text-muted-foreground text-pretty">
          Docent answers questions only from documents you add. Upload Markdown or plain text
          files to your {collection.name} collection to get started.
        </p>
        <div className="mt-2">{picker}</div>
        {messages}
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="font-serif text-question font-medium">Library</h1>
          <p className="text-muted-foreground">Documents in your {collection.name} collection</p>
        </div>
        {picker}
      </div>
      {messages}
      <ul aria-label="Documents" className="flex flex-col border-t border-border">
        {documents.map((document) => (
          <DocumentRow key={document.id} document={document} />
        ))}
      </ul>
    </div>
  );
}

function DocumentRow({ document }: { document: DocumentSummary }) {
  const failed = document.status === "failed";
  const tone = failed
    ? "text-destructive"
    : document.status === "indexed"
      ? "text-brand"
      : "text-muted-foreground";
  return (
    <li className="flex flex-col gap-1 border-b border-border py-3">
      <div className="flex items-baseline justify-between gap-4">
        <span className="min-w-0 truncate font-medium" title={document.name}>
          {document.name}
        </span>
        <span
          className={`flex shrink-0 items-center gap-1 text-meta tabular-nums transition-colors duration-150 ${tone}`}
        >
          {document.status === "indexed" && <CheckIcon aria-hidden="true" className="size-4" />}
          {STATUS_LABELS[document.status]}
        </span>
      </div>
      <span className="text-meta text-muted-foreground tabular-nums">
        {formatSize(document.size_bytes)}
      </span>
      {failed && document.failure_reason && (
        <p className="text-meta text-destructive">{document.failure_reason}</p>
      )}
    </li>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
