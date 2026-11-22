import { connection } from "next/server";

import { getApiStatus } from "@/lib/api-status";

/**
 * Says so when the API can't be reached; when it can, says nothing. Always checked at request
 * time, never cached.
 */
export async function ApiStatusMessage() {
  await connection();
  const status = await getApiStatus();

  if (status.kind === "connected") {
    return null;
  }
  return (
    <p role="status" className="px-6 py-4 text-meta text-destructive">
      Can&rsquo;t reach the server. It may be starting up; reload the page in a minute.
    </p>
  );
}
