import { connection } from "next/server";

import { getApiStatus } from "@/lib/api-status";

/** Shows whether the API is reachable. Always checked at request time, never cached. */
export async function ApiStatusMessage() {
  await connection();
  const status = await getApiStatus();

  if (status.kind === "connected") {
    return <p role="status">Server connected (version {status.version})</p>;
  }
  return (
    <p role="status">
      Can&rsquo;t reach the server. It may be starting up; reload the page in a minute.
    </p>
  );
}
