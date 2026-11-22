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
  if (response.status === 422) return { ok: false, message: NAME_TOO_LONG };
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
  if (response.status === 422) return { ok: false, message: NAME_TOO_LONG };
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

const NAME_TOO_LONG = "Keep the name to 120 characters or fewer.";

function problem(status: number): string {
  if (status === 401) return SIGNED_OUT;
  return UNREACHABLE;
}

export type InviteSummary = components["schemas"]["InviteSummary"];

/** The Collection's invites still waiting (its Owner). */
export async function listInvites(collectionId: string): Promise<Result<InviteSummary[]>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, error, response } = await caller.api.GET("/collections/{collection_id}/invites", {
    headers: caller.headers,
    params: { path: { collection_id: collectionId } },
  });
  if (data) return { ok: true, value: data };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

/** Invite an email address with a Role. Docent sends no email: the Owner passes the link on. */
export async function inviteToCollection(
  collectionId: string,
  email: string,
  role: InviteSummary["role"],
): Promise<Result<InviteSummary>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, error, response } = await caller.api.POST("/collections/{collection_id}/invites", {
    headers: caller.headers,
    params: { path: { collection_id: collectionId } },
    body: { email, role },
  });
  if (data) return { ok: true, value: data };
  if (response.status === 422) return { ok: false, message: "Enter an email address, like name@example.com." };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

/** Cancel an invite; its link stops working. */
export async function revokeInvite(inviteId: string): Promise<Result<null>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { error, response } = await caller.api.DELETE("/invites/{invite_id}", {
    headers: caller.headers,
    params: { path: { invite_id: inviteId } },
  });
  if (response.ok) return { ok: true, value: null };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

/** Join an invite's Collection, as the invited address. `wrongAccount`: signed in as another. */
export async function acceptInvite(
  inviteId: string,
): Promise<Result<CollectionSummary> | { ok: false; message: string; wrongAccount: true }> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, error, response } = await caller.api.POST("/invites/{invite_id}/accept", {
    headers: caller.headers,
    params: { path: { invite_id: inviteId } },
  });
  if (data) return { ok: true, value: data };
  if (response.status === 422) {
    return { ok: false, message: "This invite link is incomplete. Copy the whole link and try again." };
  }
  const message = detail(error) ?? problem(response.status);
  if (response.status === 403) return { ok: false, message, wrongAccount: true };
  return { ok: false, message };
}

export type MemberSummary = components["schemas"]["MemberSummary"];
/** The Roles an Owner can give: ownership moves only by transfer. */
export type MemberRole = components["schemas"]["RoleChange"]["role"];

/** Everyone with access to a Collection, Owner first (any Member). */
export async function listMembers(collectionId: string): Promise<Result<MemberSummary[]>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { data, error, response } = await caller.api.GET("/collections/{collection_id}/members", {
    headers: caller.headers,
    params: { path: { collection_id: collectionId } },
  });
  if (data) return { ok: true, value: data };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

/** Make a Member an Editor or a Viewer (the Owner). */
export async function changeRole(
  collectionId: string,
  memberId: string,
  role: MemberRole,
): Promise<Result<null>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { error, response } = await caller.api.PATCH(
    "/collections/{collection_id}/members/{member_id}",
    {
      headers: caller.headers,
      params: { path: { collection_id: collectionId, member_id: memberId } },
      body: { role },
    },
  );
  if (response.ok) return { ok: true, value: null };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

/** Remove a Member (the Owner), or leave: pass the User's own id. */
export async function removeMember(collectionId: string, memberId: string): Promise<Result<null>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { error, response } = await caller.api.DELETE(
    "/collections/{collection_id}/members/{member_id}",
    {
      headers: caller.headers,
      params: { path: { collection_id: collectionId, member_id: memberId } },
    },
  );
  if (response.ok) return { ok: true, value: null };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}

/** Make another Member the Owner; the User stays, as an Editor. */
export async function transferOwnership(
  collectionId: string,
  memberId: string,
): Promise<Result<null>> {
  const caller = await apiAsUser();
  if (!caller) return { ok: false, message: SIGNED_OUT };
  const { error, response } = await caller.api.POST("/collections/{collection_id}/owner", {
    headers: caller.headers,
    params: { path: { collection_id: collectionId } },
    body: { user_id: memberId },
  });
  if (response.ok) return { ok: true, value: null };
  return { ok: false, message: detail(error) ?? problem(response.status) };
}
