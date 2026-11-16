import { getMe } from "@/lib/me";

/** The signed-in User's Collections, Personal Collection first. */
export async function CollectionsNav() {
  const me = await getMe();
  if (!me) return null;

  return (
    <section aria-label="Collections" className="flex flex-col gap-1">
      <p className="px-2 pb-1 text-meta font-medium text-muted-foreground">Collections</p>
      <ul className="flex flex-col gap-1">
        {me.collections.map((collection) => (
          <li key={collection.id} className="rounded-md px-2 py-2 text-text-secondary">
            {collection.name}
          </li>
        ))}
      </ul>
    </section>
  );
}
