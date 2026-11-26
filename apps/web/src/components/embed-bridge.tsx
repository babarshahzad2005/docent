"use client";

import { useEffect } from "react";

/**
 * Talks to the Widget loader on the host page (public/widget.js): says when the chat is ready,
 * moves focus to the question box when the Widget opens, and asks the loader to close the
 * Widget on Escape (unless Escape is closing a source panel inside the chat).
 *
 * Render it beside the question box, inside the same Suspense boundary: its effect then runs
 * only once the box has hydrated, so "ready" means the box can take focus. (Sent earlier, the
 * focus landed on a server-rendered box that hydration then replaced.)
 */
export function EmbedBridge() {
  useEffect(() => {
    if (window.parent === window) return;
    const focusQuestion = () => document.querySelector<HTMLTextAreaElement>("textarea")?.focus();
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window.parent) return;
      if ((event.data as { docent?: string } | null)?.docent === "focus") focusQuestion();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (document.querySelector('[role="dialog"]')) return;
      window.parent.postMessage({ docent: "close" }, "*");
    };
    window.addEventListener("message", onMessage);
    window.addEventListener("keydown", onKeyDown);
    // The host page can be any site, so "*": the message carries nothing private.
    window.parent.postMessage({ docent: "ready" }, "*");
    return () => {
      window.removeEventListener("message", onMessage);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);
  return null;
}
