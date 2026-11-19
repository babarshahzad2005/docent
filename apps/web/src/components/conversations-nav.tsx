import { NavLink } from "@/components/nav-link";
import { apiAsUser } from "@/lib/api";

/** The User's recent Conversations, to reopen and continue. */
export async function ConversationsNav() {
  const caller = await apiAsUser();
  if (!caller) return null;
  const { data } = await caller.api.GET("/conversations", { headers: caller.headers });
  if (!data || data.length === 0) return null;

  return (
    <section aria-label="Conversations" className="flex min-h-0 flex-col gap-1">
      <p className="px-2 pb-1 text-meta font-medium text-muted-foreground">Conversations</p>
      <ul className="flex flex-col gap-1 overflow-y-auto">
        {data.slice(0, 20).map((conversation) => (
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
