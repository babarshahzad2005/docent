"use server";

import type { components } from "@docent/client";

import type { PassageInContext } from "@/app/passages-actions";
import { apiAsVisitor } from "@/lib/api";

export type PublicCollection = components["schemas"]["PublicCollection"];

/** A Public Collection's name, or null when it isn't public (any more) or doesn't exist. */
export async function getPublicCollection(collectionId: string): Promise<PublicCollection | null> {
  const { data, response } = await apiAsVisitor().GET("/public/{collection_id}", {
    params: { path: { collection_id: collectionId } },
  });
  if (data) return data;
  if (response.status === 404 || response.status === 422) return null;
  throw new Error(`The collection couldn’t be loaded (${response.status}).`);
}

/** A Public Collection's cited passage with the text around it, for a Visitor. */
export async function getPublicPassage(
  collectionId: string,
  chunkId: string,
): Promise<{ ok: true; value: PassageInContext | null } | { ok: false; message: string }> {
  const { data, response } = await apiAsVisitor().GET(
    "/public/{collection_id}/passages/{chunk_id}",
    { params: { path: { collection_id: collectionId, chunk_id: chunkId } } },
  );
  if (data) return { ok: true, value: data };
  if (response.status === 404 || response.status === 422) return { ok: true, value: null };
  return { ok: false, message: "The source couldn’t be loaded. Try again in a minute." };
}
