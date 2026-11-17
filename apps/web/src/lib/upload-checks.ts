/**
 * Checks the browser makes before uploading, so a file that breaks a rule is refused at once.
 * The API enforces the same rules (and the 100 MB allowance) itself; these only save a trip.
 */

export const MAX_FILE_BYTES = 20 * 1024 * 1024;
const EXTENSIONS = [".pdf", ".docx", ".md", ".markdown", ".txt"];

/** Why the file can't be uploaded, or null if it can be. Same wording as the API. */
export function precheck(file: Pick<File, "name" | "size">): string | null {
  const name = file.name;
  const extension = name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "";
  if (!EXTENSIONS.includes(extension)) {
    return `${name} can’t be added: Docent reads PDF, Word (.docx), Markdown (.md), and plain text (.txt) files.`;
  }
  if (file.size > MAX_FILE_BYTES) {
    return `${name} is ${megabytes(file.size)}, over the 20 MB limit per file. Split it into smaller files and upload those.`;
  }
  if (file.size === 0) return `${name} is empty.`;
  return null;
}

/** "8.2 MB", with a non-breaking space (DESIGN.md › Typography). */
export function megabytes(bytes: number): string {
  // Rounded up, as the API does, so a file just over a limit never reads as exactly the limit.
  return `${(Math.ceil((bytes / (1024 * 1024)) * 10) / 10).toFixed(1)} MB`;
}

/** The file's SHA-256 in lowercase hex: its fingerprint, to notice the same file uploaded twice. */
export async function sha256(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
