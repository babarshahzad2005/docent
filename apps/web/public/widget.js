/*
 * Docent Widget loader (GLOSSARY: Widget). A website adds it with one tag:
 *
 *   <script src="https://docent-tan.vercel.app/widget.js" data-collection="COLLECTION_ID" async></script>
 *
 * It adds a chat button that opens a small panel. The chat itself is an iframe served by
 * Docent (/embed/COLLECTION_ID), and the button and panel live in a shadow root, so the
 * host page's styles can't change the Widget and the Widget's can't leak into the page.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script || !script.src) return;
  var collection = script.getAttribute("data-collection");
  if (!collection || !/^[0-9a-f-]{36}$/i.test(collection)) {
    console.warn("Docent Widget: data-collection must be a collection id.");
    return;
  }
  var origin = new URL(script.src).origin;
  var embedUrl = origin + "/embed/" + encodeURIComponent(collection);

  var CHAT =
    '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>';
  var CLOSE =
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

  var css =
    ":host{all:initial}" +
    "*{box-sizing:border-box}" +
    "button{all:unset;box-sizing:border-box;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}" +
    "button:focus-visible{outline:2px solid #2f5d50;outline-offset:2px}" +
    ".open{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:56px;height:56px;border-radius:50%;" +
    "background:#2f5d50;color:#fff;box-shadow:0 4px 16px rgba(0,0,0,.25)}" +
    ".panel{position:fixed;right:16px;bottom:84px;z-index:2147483647;display:flex;flex-direction:column;" +
    "width:min(400px,calc(100vw - 32px));height:min(640px,calc(100vh - 100px));height:min(640px,calc(100dvh - 100px));overflow:hidden;" +
    "border-radius:12px;background:#f3f2ee;border:1px solid #e1dfd8;box-shadow:0 8px 32px rgba(0,0,0,.25)}" +
    ".panel[hidden]{display:none}" +
    ".bar{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:4px 4px 4px 16px;" +
    "border-bottom:1px solid #e1dfd8;font:600 14px/1.4 system-ui,sans-serif;color:#1f1e1b;background:#f3f2ee}" +
    ".close{width:44px;height:44px;border-radius:8px;color:#3f3f46}" +
    "iframe{flex:1;width:100%;border:0;background:#f3f2ee}" +
    "@media (max-width:480px){.panel{inset:0;width:100%;height:100vh;height:100dvh;border-radius:0;border:0}}" +
    "@media (prefers-color-scheme:dark){.open{background:#3f7a69}button:focus-visible{outline-color:#7fb6a4}.panel,.bar,iframe{background:#1a1a18;color:#eceae4;border-color:#34332f}" +
    ".close{color:#d4d4d8}}";

  var host = document.createElement("div");
  host.setAttribute("data-docent-widget", "");
  // Inline !important beats the host page's own rules for this element (e.g. a transform
  // that would pin the fixed-position panel to it).
  host.setAttribute("style", "all:initial !important");
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML =
    "<style>" + css + "</style>" +
    '<div class="panel" id="docent-panel" role="dialog" aria-label="Ask Docent" hidden>' +
    '<div class="bar"><span>Ask Docent</span>' +
    '<button type="button" class="close" aria-label="Close chat">' + CLOSE + "</button></div>" +
    "</div>" +
    '<button type="button" class="open" aria-label="Ask a question" aria-controls="docent-panel" aria-expanded="false">' +
    CHAT + "</button>";

  var panel = root.querySelector(".panel");
  var openButton = root.querySelector(".open");
  var closeButton = root.querySelector(".close");
  var frame = null;
  var frameReady = false;
  var phone = window.matchMedia("(max-width: 480px)");
  var madeInert = [];

  // Full screen on a phone, the panel is modal: the hidden page behind it can't take focus.
  function setPageInert(on) {
    if (on) {
      panel.setAttribute("aria-modal", "true");
      Array.prototype.forEach.call(document.body.children, function (el) {
        if (el !== host && !el.inert) {
          el.inert = true;
          madeInert.push(el);
        }
      });
    } else {
      panel.removeAttribute("aria-modal");
      madeInert.forEach(function (el) {
        el.inert = false;
      });
      madeInert = [];
    }
  }

  function focusChat() {
    if (frame && frameReady) frame.contentWindow.postMessage({ docent: "focus" }, origin);
  }

  function open() {
    if (!frame) {
      frame = document.createElement("iframe");
      frame.title = "Docent chat";
      frame.src = embedUrl;
      panel.appendChild(frame);
    }
    panel.hidden = false;
    if (phone.matches) setPageInert(true);
    openButton.setAttribute("aria-expanded", "true");
    // On a phone the panel covers the button; the panel's own Close button takes over.
    frame.focus();
    focusChat();
  }

  function close() {
    panel.hidden = true;
    setPageInert(false);
    openButton.setAttribute("aria-expanded", "false");
    openButton.focus();
  }

  openButton.addEventListener("click", function () {
    if (panel.hidden) open();
    else close();
  });
  closeButton.addEventListener("click", close);
  root.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) close();
  });
  window.addEventListener("message", function (event) {
    if (!frame || event.source !== frame.contentWindow || event.origin !== origin) return;
    var data = event.data || {};
    if (data.docent === "ready") {
      frameReady = true;
      if (!panel.hidden) focusChat();
    } else if (data.docent === "close" && !panel.hidden) {
      close();
    }
  });

  function attach() {
    document.body.appendChild(host);
  }
  if (document.body) attach();
  else document.addEventListener("DOMContentLoaded", attach);
})();
