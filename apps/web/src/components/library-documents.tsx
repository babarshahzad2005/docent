"use client";

import { CheckIcon, UploadIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  type DocumentSummary,
  finishUpload,
  listDocuments,
  startUpload,
} from "@/app/documents-actions";
import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";

const ACCEPT = ".md,.markdown,.txt,text/markdown,text/plain";
const POLL_MS = 2000;

type Status = DocumentSummary["status"];

const STATUS_LABELS: Record<Status, string> = {
  uploading: "Uploading…",
  queued: "Waiting…",
  parsing: "Reading…",
  embedding: "Indexing…",
  indexed: "Ready",
  failed: "Failed",
};

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
  const previous = useRef(new Map(initialDocuments.map((d) => [d.id, d.status])));

  const working = documents.some((d) => !isSettled(d.status));

  useEffect(() => {
    if (!working) return;
    const timer = setInterval(async () => {
      const result = await listDocuments();
      if (result.ok) setDocuments(result.value);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [working]);

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

  async function upload(files: FileList) {
    setErrors([]);
    const supabase = createClient();
    for (const file of Array.from(files)) {
      const started = await startUpload(collection.id, file.name, file.size);
      if (!started.ok) {
        setErrors((current) => [...current, started.message]);
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
        setErrors((current) => [
          ...current,
          `${file.name} couldn't be uploaded: ${error.message}. Try again.`,
        ]);
        continue;
      }
      const finished = await finishUpload(document.id);
      if (finished.ok) {
        setDocuments((current) => current.map((d) => (d.id === document.id ? finished.value : d)));
      } else {
        setErrors((current) => [...current, finished.message]);
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
          if (event.target.files?.length) void upload(event.target.files);
          event.target.value = "";
        }}
      />
      <Button size="lg" onClick={() => input.current?.click()}>
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
          {errors.map((message) => (
            <li key={message}>{message}</li>
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
  return (
    <li className="flex flex-col gap-1 border-b border-border py-3">
      <div className="flex items-baseline justify-between gap-4">
        <span className="min-w-0 truncate font-medium" title={document.name}>
          {document.name}
        </span>
        <span
          className={`flex shrink-0 items-center gap-1 text-meta tabular-nums transition-colors duration-150 ${
            failed ? "text-destructive" : document.status === "indexed" ? "text-brand" : "text-muted-foreground"
          }`}
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
