"use server";

import type { components } from "@docent/client";

import { apiAsUser } from "@/lib/api";

export type PassageInContext = components["schemas"]["PassageOut"];

/**
 * A cited passage with the text around it, or null when it no longer exists (its Document was
 * deleted) or the User can't read it any more.
 */
export async function getPassage(
  chunkId: string,
): Promise<{ ok: true; value: PassageInContext | null } | { ok: false; message: string }> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: "Your session has expired. Sign in again." };
  const { data, response } = await caller.api.GET("/passages/{chunk_id}", {
    headers: caller.headers,
    params: { path: { chunk_id: chunkId } },
  });
  if (data) return { ok: true, value: data };
  if (response.status === 404 || response.status === 422) return { ok: true, value: null };
  return { ok: false, message: "The source couldn’t be loaded. Try again in a minute." };
}
