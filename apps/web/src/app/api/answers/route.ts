import { apiBaseUrl } from "@/lib/api-status";
import { apiAsUser } from "@/lib/api";

/**
 * Streams an answer from the API to the browser. The browser can't call the API itself (it
 * holds no token the API accepts across sites), so this passes the question through with the
 * signed-in User's session and relays the server-sent events as they arrive.
 */
export async function POST(request: Request): Promise<Response> {
  // Only this site's own pages may ask: another site can't post questions as the User.
  const origin = request.headers.get("origin");
  if (origin !== null && origin !== new URL(request.url).origin) {
    return Response.json({ detail: "Not allowed." }, { status: 403 });
  }
  if (!request.headers.get("content-type")?.startsWith("application/json")) {
    return Response.json({ detail: "Send the question as JSON." }, { status: 415 });
  }
  const caller = await apiAsUser();
  if (!caller) {
    return Response.json({ detail: "Your session has expired. Sign in again." }, { status: 401 });
  }
  const upstream = await fetch(`${apiBaseUrl()}/answers`, {
    method: "POST",
    headers: { ...caller.headers, "Content-Type": "application/json" },
    body: await request.text(),
    signal: request.signal, // the reader left: stop asking the API for more
  });
  if (!upstream.ok || !upstream.body) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
    });
  }
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
