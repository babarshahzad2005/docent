import { useSyncExternalStore } from "react";

const noChanges = () => () => {};

/**
 * False while rendering on the server (and hydrating), true in the browser. For what depends on
 * the reader, like dates in their time zone: shown only in the browser, they can't differ from
 * the server's render and break hydration.
 */
export function useInBrowser(): boolean {
  return useSyncExternalStore(
    noChanges,
    () => true,
    () => false,
  );
}
