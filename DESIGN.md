# Docent Design System

The visual and interaction rules for every Docent screen. If a component or screen disagrees with this file, either the component changes or this file does, in the same pull request.

## Principles

1. **Reading comes first.** Answers and source passages are long-form text. Type, measure, and contrast are tuned for reading, not for scanning dashboards.
2. **Show where every answer came from.** The highlighter, which ties a citation in the answer to a passage in the source, is Docent's one signature element. It gets the boldness; everything around it stays quiet.
3. **Calm surface, rigorous detail.** The interface is warm and unhurried. Precision lives in the details: verification status, dates, page numbers, and the "How this was answered" view.
4. **Motion only with a purpose.** Things move to show where something came from or what changed, never to decorate.
5. **Accessible as a baseline.** WCAG 2.2 AA is the floor, not a goal.

## Color

Light mode is the primary theme. Dark mode is supported from the first release.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F3F2EE` | `#1A1A18` | App background |
| `--surface` | `#FFFFFF` | `#22221F` | Source panel, cards, inputs |
| `--surface-muted` | `#E8E6DF` | `#2B2B27` | Selected rows |
| `--border` | `#E1DFD8` | `#34332F` | Dividers, pane edges |
| `--border-strong` | `#D3D0C6` | `#45443F` | Buttons, inputs |
| `--text` | `#1F1E1B` | `#ECEAE4` | Primary text |
| `--text-secondary` | `#3D3A34` | `#CFCBC2` | Secondary nav items |
| `--text-muted` | `#625E55` | `#A8A49A` | Labels, metadata, placeholders |
| `--text-context` | `#6F6A60` | `#9E998E` | Source text around the cited passage |
| `--brand` | `#2F5D50` | `#7FB6A4` | Links, focus outline, verification |
| `--brand-strong` | `#1F4238` | `#A6D1C2` | Link hover |
| `--brand-button` | `#2F5D50` | `#3F7A69` | Primary button background (white text) |
| `--brand-subtle` | `#E7F0EC` | `#22332D` | Scope chip background |
| `--brand-subtle-text` | `#234A3F` | `#A6D1C2` | Scope chip text |
| `--danger` | `#B42318` | `#F97066` | Destructive actions and errors (always with text) |
| `--scrim` | `rgb(31 30 27 / 0.24)` | `rgb(0 0 0 / 0.5)` | Backdrop behind drawers and dialogs |
| `--mark` | `#F6E3AE` | `#4A3D17` | Highlighter background |
| `--mark-edge` | `#D9A72E` | `#C99A2E` | Highlighter underline |
| `--mark-text` | `#5E4310` | `#F2D58A` | Citation number on the mark |
| `--warning-icon` | `#9A6516` | `#D9A72E` | "Documents disagree" icon (paired with text) |

Rules:

- Every text color passes 4.5:1 against the backgrounds it sits on; large text (24px+) passes 3:1. Check new pairs before adding them.
- The highlighter colors (`--mark*`) mean "this is cited." Never use them for warnings, selection, or decoration.
- Color never carries meaning alone: the conflict notice has an icon and a heading, verification has a check mark and words.
- No gradient washes, no decorative textures.
- The brand color is named `--brand`, not "accent": the component library uses "accent" for hover surfaces, and the code maps its names onto these tokens.

## Typography

Two families. Newsreader is for reading, Inter is for the interface.

| Role | Family | Size | Line height | Weight | Tracking |
|---|---|---|---|---|---|
| Question (`h1`) | Newsreader | 1.75rem | 1.25 | 500 | -0.01em |
| Source heading | Newsreader | 1.5rem | 1.25 | 500 | -0.01em |
| Answer body | Newsreader | 1.1875rem | 1.65 | 400 (600 for emphasis) | 0 |
| Source body | Newsreader | 1.0625rem | 1.75 | 400 | 0 |
| Wordmark | Newsreader | 1.375rem | 1.2 | 500 | -0.01em |
| UI body | Inter | 0.9375rem | 1.55 | 400 / 500 | 0 |
| UI small, metadata | Inter | 0.8125rem | 1.5 | 400 / 500 | 0 |
| Citation number | Inter | 0.75rem | 1 | 600 | 0 |
| Inputs | Inter | 1rem | 1.5 | 400 | 0 |

Rules:

- Sizes in `rem`, line heights unitless.
- Answers cap at 40rem (about 70 characters per line); source text caps at 34em.
- Inputs are 16px or larger at every viewport so tablets don't zoom.
- `font-variant-numeric: tabular-nums` on counts, dates, page numbers, and anything that updates.
- `text-wrap: balance` on the question; `text-wrap: pretty` on paragraphs.
- Sentence case everywhere. No all-caps labels.
- Typographic punctuation in rendered text (curly quotes, en and em dashes, `…`); non-breaking spaces inside values like "16&nbsp;weeks" and "1&nbsp;March".
- Font smoothing is set once on the root.

## Spacing, shape, and depth

- **Spacing scale** (px): 4, 8, 12, 16, 20, 24, 28, 32, 40, 48. Nothing off-scale.
- **Radius** follows hierarchy: 4 for marks and citation numbers, 8 for rows and small buttons, 10 for buttons, 12 for cards, 14 for the question box, full for pills.
- **Depth** comes from borders and surface color, not shadows. One shadow token exists for floating layers only (menus, popovers, dialogs): `0 8px 24px rgb(31 30 27 / 0.12)`.

## Layout

```
┌──────────┬───────────────────────────────┬────────────────────────┐
│ Library  │ Scope chips                   │ Source (when open)     │
│ 248px    │ Question                      │ min 420px              │
│          │ Answer (max 40rem)            │ Title, location, date  │
│          │ Conflict notice               │ Context ─ MARK ─ ctx   │
│          │ Verification · actions        │ Actions                │
│          │ Ask a follow-up               │                        │
└──────────┴───────────────────────────────┴────────────────────────┘
```

- Content aligns to the start edge. Nothing is centered except empty states.
- **≥ 1280px:** three panes side by side.
- **1024–1279px:** the source opens as a sheet over the answer from the right.
- **< 1024px (tablet portrait):** the library collapses into a drawer; the source opens as a full-height sheet.
- Every interactive target is at least 32px (44px for primary actions and anything used on touch).

## Signature components

- **Citation number:** a small `--mark` chip with a 2px `--mark-edge` underline, inline after the claim it supports. Its accessible name states the source, e.g. "Source 1, Parental Leave Policy 2026, page 3".
- **Highlighted passage:** the cited text in the source wrapped in `<mark>` with the same `--mark` and `--mark-edge`. Surrounding text uses `--text-context`, so the passage reads first without the rest becoming illegible.
- **Conflict notice:** a bordered surface with an icon, the heading "Your documents disagree", and a table of each value, its document, and its Effective Date, newest first.
- **Verification line:** a check mark and "All N citations checked against their source". If claims were removed, it says how many.
- **Scope chips:** pill-shaped, `--brand-subtle` with `--brand-subtle-text`; "Add a collection" is a dashed pill.

## Motion

Purposeful and quick. Tokens:

```css
--ease-out: cubic-bezier(0.23, 1, 0.32, 1);
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
```

| Interaction | Animates? | Purpose | Spec |
|---|---|---|---|
| Keyboard shortcuts, command menu | **No** | — | Instant |
| Streaming answer text | **No** per-token motion | Text is being read | Tokens append in place; a static caret marks the end and is removed when done |
| Hover on rows, links, buttons | Color only | Feedback | 120ms `ease`, only under `(hover: hover) and (pointer: fine)` |
| Press on buttons | Yes | Feedback | `scale(0.97)`, 100ms `--ease-out` |
| Source pane opening (wide screens) | Yes | Spatial consistency | `opacity` 0→1 and `translateX(24px)`→0, 240ms `--ease-out`; closes the same way in 200ms |
| Source sheet (narrower screens) | Yes | Spatial consistency | `translateX(100%)`→0, 300ms `--ease-drawer`; exits the way it entered |
| Scroll to cited passage | Yes | State indication | Smooth scroll, then the mark fades in over 180ms `--ease-out` once the passage is in view |
| Unsupported claim removed after verification | Yes | Preventing a jarring change | Sentence fades out over 150ms, then the verification line updates |
| Menus, popovers, tooltips | Yes | Spatial consistency | `scale(0.97)` + `opacity`, 150–200ms `--ease-out`, origin at the trigger |
| Confirmation dialogs | Yes | State indication | `scale(0.97)` + `opacity`, 200ms `--ease-out`, centered |
| Toasts | Yes | Feedback | CSS transitions (never keyframes), enter and exit from the bottom |
| Document status (queued → indexed) | Color only | State indication | 150ms crossfade |

Rules:

- Only `transform` and `opacity` animate (plus `clip-path` where needed). Never `transition: all`, never `scale(0)`, never `ease-in`.
- UI motion stays under 300ms; sheets and toasts are the only exceptions.
- **Reduced motion:** drop every transform and keep opacity fades at the same timing; scrolling becomes instant.

## Accessibility

- WCAG 2.2 AA minimum, checked with automated audits in CI plus manual keyboard and screen-reader passes before each release.
- Native elements first: `<button>`, `<a href>`, `<input>` with a `<label>`, `<table>` for tabular data, `<mark>` for highlights.
- Visible focus everywhere: a 2px `--brand` outline with a 2px offset. Components never replace it with their own ring.
- One `h1` per screen (the question in a Conversation); headings descend in order.
- Landmarks: library `nav`, answer `main`, source `aside` with a label.
- Streaming answers are announced politely (`aria-live="polite"`) once complete, not per token.

## Writing

- Name things the way users think of them: "Collection", "Document", "Search in", not system terms. Use the words in [GLOSSARY.md](GLOSSARY.md).
- Buttons say what happens: "Ask", "Open full document", "Add a collection".
- A Decline is direct and helpful: "I couldn't find that in your documents," followed by the closest passages.
- Errors say what happened and how to fix it, never apologize, never stay vague.
- Empty states invite the next action: an empty Library offers one thing to do, which is upload.

## Avoid

- All-caps eyebrow labels, metadata joined with middle dots, monospace for small labels.
- Cream-and-clay palettes, gradient washes, glows, textures.
- Identical rounded cards with the same shadow for every piece of content.
- Emoji as icons; use stroke icons with `aria-hidden` and a text label or `aria-label`.
- Motion on anything a user triggers dozens of times a day.
