import { connection } from "next/server";
import { cache } from "react";

import { NavLink } from "@/components/nav-link";
import { apiAsUser } from "@/lib/api";

const SHOWN = 20;

/** The User's recent Conversations; cached per request, as the navigation renders twice. */
const recentConversations = cache(async () => {
  await connection(); // request-time only, like the session it reads
  const caller = await apiAsUser();
  if (!caller) return [];
  try {
    const { data } = await caller.api.GET("/conversations", {
      headers: caller.headers,
      params: { query: { limit: SHOWN } },
    });
    return data ?? [];
  } catch {
    return []; // the list is a convenience: the page works without it
  }
});

/** The User's recent Conversations, to reopen and continue. */
export async function ConversationsNav() {
  const conversations = await recentConversations();
  if (conversations.length === 0) return null;

  return (
    <section aria-label="Conversations" className="flex min-h-0 flex-col gap-1">
      <p className="px-2 pb-1 text-meta font-medium text-muted-foreground">Conversations</p>
      <ul className="flex flex-col gap-1 overflow-y-auto">
        {conversations.map((conversation) => (
          <li key={conversation.id} className="min-w-0">
            <NavLink href={`/conversations/${conversation.id}`}>
              <span className="block truncate" title={conversation.title}>
                {conversation.title}
              </span>
            </NavLink>
          </li>
        ))}
      </ul>
    </section>
  );
}
