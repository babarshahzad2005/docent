/** A moment's date where the reader is: "6 December 2026", from an ISO timestamp. */
export function formatLocalDate(isoDateTime: string): string {
  return new Date(isoDateTime).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/** A date as people write it: "1 January 2024", from an ISO date ("2024-01-01"). */
export function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}
