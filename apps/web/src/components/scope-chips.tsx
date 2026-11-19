"use client";

import { PlusIcon, XIcon } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

export type CollectionChoice = { id: string; name: string; is_demo?: boolean };

/**
 * The Scope a new question starts with: the User's own Collections. The Demo Collection is
 * one they can ask, not one of theirs, so it is offered under "Add a collection" (PRD
 * decision log, 2026-11-19) unless it is all they have.
 */
export function defaultScope(collections: CollectionChoice[]): string[] {
  const own = collections.filter((collection) => !collection.is_demo);
  return (own.length > 0 ? own : collections).map((collection) => collection.id);
}

/**
 * The Scope of the next question, as chips (DESIGN.md › Answer): the Collections it will be
 * answered from, each removable while another is left, and "Add a collection" for the rest.
 */
export function ScopeChips({
  collections,
  value,
  onChange,
}: {
  collections: CollectionChoice[];
  value: string[];
  onChange: (scope: string[]) => void;
}) {
  const [adding, setAdding] = useState(false);
  const listId = useId();
  const group = useRef<HTMLDivElement>(null);
  // The button just used disappears with its choice: keep focus in the chips.
  const refocus = useRef(false);
  useEffect(() => {
    if (!refocus.current) return;
    refocus.current = false;
    const next = group.current?.querySelector<HTMLElement>("[data-chip-action]");
    (next ?? group.current)?.focus();
  }, [value]);
  const choose = (scope: string[]) => {
    refocus.current = true;
    onChange(scope);
  };
  const chosen = collections.filter((collection) => value.includes(collection.id));
  const others = collections.filter((collection) => !value.includes(collection.id));
  if (collections.length === 0) return null;

  return (
    <div ref={group} tabIndex={-1} className="flex flex-col gap-2 outline-none">
      <ul aria-label="Collections to ask" className="flex flex-wrap items-center gap-2">
        {chosen.map((collection) => (
          <li
            key={collection.id}
            className="flex h-8 items-center gap-1 rounded-full bg-brand-subtle pr-1 pl-3 text-meta font-medium text-brand-subtle-text pointer-coarse:h-11"
          >
            {collection.name}
            {chosen.length > 1 && (
              <button
                type="button"
                aria-label={`Don’t ask ${collection.name}`}
                data-chip-action
                onClick={() => choose(value.filter((id) => id !== collection.id))}
                className="flex size-6 cursor-pointer items-center justify-center rounded-full pointer-coarse:size-11 [@media(hover:hover)_and_(pointer:fine)]:hover:bg-brand-subtle-text/10"
              >
                <XIcon aria-hidden="true" className="size-3.5" />
              </button>
            )}
          </li>
        ))}
        {others.length > 0 && (
          <li>
            <button
              type="button"
              aria-expanded={adding}
              aria-controls={adding ? listId : undefined}
              data-chip-action
              onClick={() => setAdding((open) => !open)}
              className="flex h-8 cursor-pointer items-center gap-1 rounded-full border border-dashed border-border-strong px-3 text-meta text-text-secondary pointer-coarse:h-11 [@media(hover:hover)_and_(pointer:fine)]:hover:border-brand"
            >
              <PlusIcon aria-hidden="true" className="size-3.5" />
              Add a collection
            </button>
          </li>
        )}
      </ul>
      {adding && others.length > 0 && (
        <ul id={listId} aria-label="Collections you can add" className="flex flex-wrap gap-2">
          {others.map((collection) => (
            <li key={collection.id}>
              <button
                type="button"
                onClick={() => {
                  choose([...value, collection.id]);
                  setAdding(false);
                }}
                className="h-8 cursor-pointer rounded-full border border-border px-3 text-meta pointer-coarse:h-11 [@media(hover:hover)_and_(pointer:fine)]:hover:border-brand"
              >
                {collection.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** "Asked of Personal and Demo Collection": the Scope an answer used. */
export function scopeNames(scope: string[], collections: CollectionChoice[]): string | null {
  const names = scope
    .map((id) => collections.find((collection) => collection.id === id)?.name)
    .filter((name): name is string => Boolean(name));
  if (names.length === 0) return null;
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
