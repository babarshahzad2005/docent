"use server";

import type { components } from "@docent/client";
import { after } from "next/server";

import { detail, type Result, SIGNED_OUT, UNREACHABLE } from "@/lib/action-result";
import { apiAsUser } from "@/lib/api";

export type DocumentSummary = components["schemas"]["DocumentSummary"];
export type UploadTarget = components["schemas"]["UploadTarget"];

/** Every Document in the User's Collections, for refreshing statuses. */
export async function listDocuments(): Promise<Result<DocumentSummary[]>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, response } = await caller.api.GET("/documents", { headers: caller.headers });
  return data ? { ok: true, value: data } : { ok: false, message: problem(response.status) };
}

/**
 * Create the Document and get where to upload its file. `duplicate` is set when the Collection
 * already has a Document with the same content, so the User can choose to keep both.
 */
export async function startUpload(
  collectionId: string,
  name: string,
  sizeBytes: number,
  sha256: string,
  allowDuplicate = false,
  /** The Document this file Replaces (GLOSSARY: Replace), if any. */
  replaces?: string,
): Promise<
  | { ok: true; value: { document: DocumentSummary; upload: UploadTarget } }
  | { ok: false; message: string; duplicate: boolean }
> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT, duplicate: false };
  const { data, error, response } = await caller.api.POST("/documents", {
    headers: caller.headers,
    body: {
      collection_id: collectionId,
      name,
      size_bytes: sizeBytes,
      sha256,
      allow_duplicate: allowDuplicate,
      replaces: replaces ?? null,
    },
  });
  if (data) return { ok: true, value: data };
  return {
    ok: false,
    message: detail(error) ?? problem(response.status),
    duplicate: response.status === 409,
  };
}

/**
 * The file is stored: queue the Document, then start processing it once the response is sent.
 * Processing continues after the browser has its answer, so the Library can show progress.
 */
export async function finishUpload(documentId: string): Promise<Result<DocumentSummary>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, response } = await caller.api.POST("/documents/{document_id}/uploaded", {
    headers: caller.headers,
    params: { path: { document_id: documentId } },
  });
  if (!data) return { ok: false, message: problem(response.status) };
  processInBackground(caller);
  return { ok: true, value: data };
}

/** Delete a Document with its file, passages, and vectors. */
export async function deleteDocument(documentId: string): Promise<Result<null>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { error, response } = await caller.api.DELETE("/documents/{document_id}", {
    headers: caller.headers,
    params: { path: { document_id: documentId } },
  });
  if (response.ok) return { ok: true, value: null };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

/** Set the date a Document's content applies from (Owners and Editors). */
export async function setEffectiveDate(
  documentId: string,
  effectiveDate: string,
): Promise<Result<DocumentSummary>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, error, response } = await caller.api.PATCH("/documents/{document_id}", {
    headers: caller.headers,
    params: { path: { document_id: documentId } },
    body: { effective_date: effectiveDate },
  });
  if (data) return { ok: true, value: data };
  if (response.status === 422) {
    return { ok: false, message: "Choose a date between 1900 and 2100." };
  }
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

/** Queue a failed Document again and start processing it. */
export async function retryDocument(documentId: string): Promise<Result<DocumentSummary>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, response } = await caller.api.POST("/documents/{document_id}/retry", {
    headers: caller.headers,
    params: { path: { document_id: documentId } },
  });
  if (!data) return { ok: false, message: problem(response.status) };
  processInBackground(caller);
  return { ok: true, value: data };
}

/**
 * Starts a batch after the response is sent, so a new Document doesn't wait for the scheduler's
 * next minute. The function stays alive until the batch finishes.
 */
function processInBackground(caller: NonNullable<Awaited<ReturnType<typeof apiAsUser>>>) {
  after(async () => {
    await caller.api.POST("/ingestion/run", { headers: caller.headers });
  });
}

function problem(status: number): string {
  if (status === 401) return SIGNED_OUT;
  if (status === 403) {
    return "Only this collection’s owner and editors can add or change documents. Ask its owner to make you an editor.";
  }
  return UNREACHABLE;
}
