/**
 * The Scope of a question: which Collections it is answered from. Shared by server pages and
 * client components, so it lives outside any "use client" module (a server page can't call a
 * function from one).
 */

export type CollectionChoice = { id: string; name: string; is_demo?: boolean };

/**
 * The Scope a new question starts with: the User's Collections, their own and those shared
 * with them. The Demo Collection is one they can ask, not one of theirs, so it is offered
 * under "Add a collection" (PRD decision log, 2026-11-19 and 2026-11-22) unless it is all
 * they have.
 */
export function defaultScope(collections: CollectionChoice[]): string[] {
  const own = collections.filter((collection) => !collection.is_demo);
  return (own.length > 0 ? own : collections).map((collection) => collection.id);
}

/**
 * Where a Document in `currentId` can be Moved (GLOSSARY: Move): the User's other Collections
 * where they are an Owner or Editor, never the Demo Collection.
 */
export function moveTargets(
  collections: (CollectionChoice & { role: string })[],
  currentId: string,
): { id: string; name: string }[] {
  return collections
    .filter((c) => c.id !== currentId && !c.is_demo && (c.role === "owner" || c.role === "editor"))
    .map(({ id, name }) => ({ id, name }));
}
