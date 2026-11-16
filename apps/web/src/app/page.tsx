import { UploadIcon } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";

export default function LibraryPage() {
  return (
    <AppShell>
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-4 px-4 py-24 text-center">
        <h1 className="font-serif text-question font-medium text-balance">
          Your library is empty
        </h1>
        <p className="text-muted-foreground">
          Docent answers questions only from documents you add. Upload PDFs, Word files, Markdown,
          or plain text to get started.
        </p>
        <Button size="lg" className="mt-2">
          <UploadIcon aria-hidden="true" />
          Upload documents
        </Button>
      </div>
    </AppShell>
  );
}
