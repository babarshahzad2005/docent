import { createDocentClient, type DocentClient } from "@docent/client";

export type ApiStatus =
  | { kind: "connected"; version: string }
  | { kind: "unreachable"; reason: string };

/**
 * The API's base URL. Called from the server, except by a Visitor's browser asking a Public
 * Collection, so the API counts the Visitor's own address against its rate limits (#94).
 */
export function apiBaseUrl(): string {
  return process.env.API_BASE_URL ?? "http://localhost:8000";
}

/** Ask the API's health endpoint whether it is up, giving up after `timeoutMs`. */
export async function getApiStatus(
  client: DocentClient = createDocentClient(apiBaseUrl()),
  timeoutMs = 3000,
): Promise<ApiStatus> {
  try {
    const { data, response } = await client.GET("/health", {
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (data) return { kind: "connected", version: data.version };
    return { kind: "unreachable", reason: `The API answered with status ${response.status}.` };
  } catch {
    return { kind: "unreachable", reason: "The API didn't respond." };
  }
}
