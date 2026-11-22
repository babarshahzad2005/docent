import type { CollectionSummary } from "@/app/collections-actions";
import { NewCollection } from "@/components/collection-settings";
import { NavLink } from "@/components/nav-link";
import { getMe } from "@/lib/me";

/**
 * The signed-in User's Collections: their own (Personal first) and the Demo Collection, then
 * those others shared with them (FLOWS › Share: "Shared with me").
 */
export async function CollectionsNav() {
  const me = await getMe();
  if (!me) return null;
  const shared = me.collections.filter((c) => c.role !== "owner" && !c.is_demo);
  const own = me.collections.filter((c) => !shared.includes(c));

  return (
    <>
      <section aria-label="Collections" className="flex flex-col gap-1">
        <p className="px-2 pb-1 text-meta font-medium text-muted-foreground">
          Collections
        </p>
        <CollectionLinks collections={own} />
        <NewCollection />
      </section>
      {shared.length > 0 && (
        <section aria-label="Shared with me" className="flex flex-col gap-1">
          <p className="px-2 pb-1 text-meta font-medium text-muted-foreground">
            Shared with me
          </p>
          <CollectionLinks collections={shared} />
        </section>
      )}
    </>
  );
}

function CollectionLinks({
  collections,
}: {
  collections: CollectionSummary[];
}) {
  return (
    <ul className="flex flex-col gap-1">
      {collections.map((collection) => (
        <li key={collection.id}>
          <NavLink
            href={
              collection.is_personal ? "/" : `/collections/${collection.id}`
            }
          >
            {collection.name}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}
