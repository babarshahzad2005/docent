"use server";

import type { components } from "@docent/client";
import { after } from "next/server";

import { apiAsUser } from "@/lib/api";

export type DocumentSummary = components["schemas"]["DocumentSummary"];
export type UploadTarget = components["schemas"]["UploadTarget"];

type Result<T> = { ok: true; value: T } | { ok: false; message: string };

const SIGNED_OUT = "Your session has expired. Sign in again.";
const UNREACHABLE = "Can't reach the server. Try again in a minute.";

/** Every Document in the User's Collections, for refreshing statuses. */
export async function listDocuments(): Promise<Result<DocumentSummary[]>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, response } = await caller.api.GET("/documents", { headers: caller.headers });
  return data ? { ok: true, value: data } : { ok: false, message: problem(response.status) };
}

/** Create the Document and get where to upload its file. */
export async function startUpload(
  collectionId: string,
  name: string,
  sizeBytes: number,
): Promise<Result<{ document: DocumentSummary; upload: UploadTarget }>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, error, response } = await caller.api.POST("/documents", {
    headers: caller.headers,
    body: { collection_id: collectionId, name, size_bytes: sizeBytes },
  });
  if (data) return { ok: true, value: data };
  return { ok: false, message: detail(error) ?? problem(response.status) };
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
  after(async () => {
    await caller.api.POST("/ingestion/run", { headers: caller.headers });
  });
  return { ok: true, value: data };
}

function detail(error: unknown): string | undefined {
  if (error && typeof error === "object" && "detail" in error && typeof error.detail === "string") {
    return error.detail;
  }
  return undefined;
}

function problem(status: number): string {
  if (status === 401) return SIGNED_OUT;
  if (status === 403) return "You can't add documents to this collection.";
  return UNREACHABLE;
}
