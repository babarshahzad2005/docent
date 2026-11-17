import { describe, expect, it } from "vitest";

import { MAX_FILE_BYTES, megabytes, precheck, sha256 } from "./upload-checks";

describe("precheck", () => {
  it.each(["report.pdf", "Notes.DOCX", "readme.md", "a.markdown", "plain.txt"])(
    "accepts %s",
    (name) => {
      expect(precheck({ name, size: 10 })).toBeNull();
    },
  );

  it("refuses other types, naming what Docent reads", () => {
    expect(precheck({ name: "slides.pptx", size: 10 })).toBe(
      "slides.pptx can’t be added: Docent reads PDF, Word (.docx), Markdown (.md), and plain text (.txt) files.",
    );
    expect(precheck({ name: "no-extension", size: 10 })).toMatch(/can’t be added/);
  });

  it("refuses files over 20 MB, naming the limit and the fix", () => {
    expect(precheck({ name: "big.pdf", size: MAX_FILE_BYTES + 1 })).toBe(
      "big.pdf is 20.0 MB, over the 20 MB limit per file. Split it into smaller files and upload those.",
    );
    expect(precheck({ name: "edge.pdf", size: MAX_FILE_BYTES })).toBeNull();
  });

  it("refuses empty files", () => {
    expect(precheck({ name: "empty.txt", size: 0 })).toBe("empty.txt is empty.");
  });
});

describe("megabytes", () => {
  it("rounds to one decimal with a non-breaking space", () => {
    expect(megabytes(8.24 * 1024 * 1024)).toBe("8.2 MB");
  });
});

describe("sha256", () => {
  it("fingerprints a file's bytes", async () => {
    expect(await sha256(new Blob(["abc"]))).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });
});
