import { apiBaseUrl } from "@/lib/api-status";

/**
 * Streams a Visitor's answer from a Public Collection (GLOSSARY: Visitor). Like
 * `/api/answers`, but with no session: the API answers only while the Collection is public.
 */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  // Only this site's own pages ask through here.
  const origin = request.headers.get("origin");
  if (origin !== null && origin !== new URL(request.url).origin) {
    return Response.json({ detail: "Not allowed." }, { status: 403 });
  }
  if (!request.headers.get("content-type")?.startsWith("application/json")) {
    return Response.json({ detail: "Send the question as JSON." }, { status: 415 });
  }
  const { id } = await params;
  const upstream = await fetch(`${apiBaseUrl()}/public/${encodeURIComponent(id)}/answers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
