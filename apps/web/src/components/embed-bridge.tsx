"use client";

import { useEffect } from "react";

// The host page can be any site, so messages go to "*": they carry nothing private.
function tellLoader(docent: "ready" | "close") {
  window.parent.postMessage({ docent }, "*");
}

/**
 * Asks the Widget loader on the host page (public/widget.js) to close the Widget on Escape,
 * unless Escape is closing a source panel inside the chat. Render it outside Suspense, so
 * Escape works while the chat is still loading.
 */
export function EmbedEscape() {
  useEffect(() => {
    if (window.parent === window) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (document.querySelector('[role="dialog"]')) return;
      tellLoader("close");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
  return null;
}

/**
 * Tells the Widget loader the chat is ready, and moves focus to the question box when the
 * Widget opens. Render it beside the question box, inside the same Suspense boundary: its
 * effect then runs only once the box has hydrated, so "ready" means the box can take focus.
 */
export function EmbedBridge() {
  useEffect(() => {
    if (window.parent === window) return;
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window.parent) return;
      if ((event.data as { docent?: string } | null)?.docent === "focus") {
        document.querySelector<HTMLTextAreaElement>("textarea")?.focus();
      }
    };
    window.addEventListener("message", onMessage);
    tellLoader("ready");
    return () => window.removeEventListener("message", onMessage);
  }, []);
  return null;
}
