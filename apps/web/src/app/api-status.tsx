import { connection } from "next/server";

import { getApiStatus } from "@/lib/api-status";

/** Shows whether the API is reachable. Always checked at request time, never cached. */
export async function ApiStatusMessage() {
  await connection();
  const status = await getApiStatus();

  if (status.kind === "connected") {
    return <p role="status">API connected (version {status.version}).</p>;
  }
  return (
    <p role="status">
      API not reachable. {status.reason} Start it with <code>pnpm dev</code> from the repository
      root.
    </p>
  );
}
