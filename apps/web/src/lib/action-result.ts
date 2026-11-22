/** What a server action returns: its value, or a message for the User saying what went wrong. */
export type Result<T> = { ok: true; value: T } | { ok: false; message: string };

export const SIGNED_OUT = "Your session has expired. Sign in again.";
export const UNREACHABLE = "Can’t reach the server. Try again in a minute.";

/** The API's own explanation (FastAPI's `detail`), when it gave one. */
export function detail(error: unknown): string | undefined {
  if (error && typeof error === "object" && "detail" in error && typeof error.detail === "string") {
    return error.detail;
  }
  return undefined;
}
