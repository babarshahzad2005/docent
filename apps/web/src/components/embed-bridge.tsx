"use client";

import { useEffect } from "react";

/**
 * Talks to the Widget loader on the host page (public/widget.js): says when the chat is ready,
 * moves focus to the question box when the Widget opens, and asks the loader to close the
 * Widget on Escape (unless Escape is closing a source panel inside the chat).
 */
export function EmbedBridge() {
  useEffect(() => {
    if (window.parent === window) return;
    let waiting: MutationObserver | null = null;
    // The question box arrives once the collection has loaded, which can be after "ready".
    const focusQuestion = () => {
      const box = document.querySelector<HTMLTextAreaElement>("textarea");
      if (box) return box.focus();
      waiting?.disconnect();
      waiting = new MutationObserver(() => {
        const found = document.querySelector<HTMLTextAreaElement>("textarea");
        if (!found) return;
        waiting?.disconnect();
        waiting = null;
        found.focus();
      });
      waiting.observe(document.body, { childList: true, subtree: true });
    };
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
      waiting?.disconnect();
    };
  }, []);
  return null;
}
