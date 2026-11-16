import createClient from "openapi-fetch";

import type { paths } from "./schema";

/** Typed client for the Docent API, generated from its OpenAPI schema. */
export function createDocentClient(baseUrl: string, options: { fetch?: typeof fetch } = {}) {
  return createClient<paths>({ baseUrl, fetch: options.fetch });
}

export type DocentClient = ReturnType<typeof createDocentClient>;

export type { components, paths } from "./schema";
