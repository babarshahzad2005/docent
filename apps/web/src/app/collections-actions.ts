"use server";

import type { components } from "@docent/client";

import { detail, type Result, SIGNED_OUT, UNREACHABLE } from "@/lib/action-result";
import { apiAsUser } from "@/lib/api";

export type CollectionSummary = components["schemas"]["CollectionSummary"];

/** A new, empty Collection owned by the User. */
export async function createCollection(name: string): Promise<Result<CollectionSummary>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, error, response } = await caller.api.POST("/collections", {
    headers: caller.headers,
    body: { name },
  });
  if (data) return { ok: true, value: data };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

/** Rename a Collection (its Owner). */
export async function renameCollection(
  collectionId: string,
  name: string,
): Promise<Result<CollectionSummary>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, error, response } = await caller.api.PATCH("/collections/{collection_id}", {
    headers: caller.headers,
    params: { path: { collection_id: collectionId } },
    body: { name },
  });
  if (data) return { ok: true, value: data };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

/** Delete a Collection with all its Documents (its Owner). */
export async function deleteCollection(collectionId: string): Promise<Result<null>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { error, response } = await caller.api.DELETE("/collections/{collection_id}", {
    headers: caller.headers,
    params: { path: { collection_id: collectionId } },
  });
  if (response.ok) return { ok: true, value: null };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

function problem(status: number): string {
  if (status === 401) return SIGNED_OUT;
  if (status === 422) return "Keep the name to 120 characters or fewer.";
  return UNREACHABLE;
}
