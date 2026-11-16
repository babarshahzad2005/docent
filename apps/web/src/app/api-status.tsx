import { getApiStatus } from "@/lib/api-status";

export async function ApiStatusMessage() {
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
