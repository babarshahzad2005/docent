import { Suspense } from "react";

import { ApiStatusMessage } from "./api-status";

export default function Home() {
  return (
    <main>
      <h1>Docent</h1>
      <Suspense fallback={<p role="status">Checking the API…</p>}>
        <ApiStatusMessage />
      </Suspense>
    </main>
  );
}
