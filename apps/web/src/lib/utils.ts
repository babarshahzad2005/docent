import { createCn } from "cn/config";

/**
 * Merges class names, resolving Tailwind conflicts. Docent's type scale (DESIGN.md › Typography)
 * is registered as font sizes so `text-ui` and a text color like `text-primary-foreground`
 * are both kept instead of one replacing the other.
 */
export const cn = createCn({
  extend: {
    classGroups: {
      "font-size": [
        { text: ["question", "heading", "answer", "source", "wordmark", "ui", "meta", "cite"] },
      ],
    },
  },
});
