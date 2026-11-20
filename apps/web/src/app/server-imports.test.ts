import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

function isClient(path: string): boolean {
  for (const candidate of [`${path}.tsx`, `${path}.ts`, join(path, "index.tsx")]) {
    try {
      return /^\s*["']use client["']/.test(readFileSync(candidate, "utf8"));
    } catch {
      // try the next extension
    }
  }
  return false;
}

/**
 * A server component can render a client component, but can't call a function from a
 * "use client" module: Next.js throws at request time, and neither the build nor the type
 * check notices. Shared helpers belong in a module without the directive (src/lib).
 */
describe("Server components", () => {
  it("never call a function from a \"use client\" module", () => {
    const problems: string[] = [];
    for (const file of files(join(SRC, "app"))) {
      const source = readFileSync(file, "utf8");
      if (/^\s*["']use client["']/.test(source)) continue;
      for (const match of source.matchAll(/import\s+\{([^}]*)\}\s+from\s+["']@\/([^"']+)["']/g)) {
        const names = match[1]
          .split(",")
          .map((name) => name.trim())
          .filter((name) => name && !name.startsWith("type "));
        const functions = names.filter((name) => /^[a-z]/.test(name));
        if (functions.length > 0 && isClient(join(SRC, match[2]))) {
          problems.push(`${file.slice(SRC.length)} imports ${functions.join(", ")} from @/${match[2]}`);
        }
      }
    }
    expect(problems).toEqual([]);
  });
});
