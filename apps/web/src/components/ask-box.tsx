"use client";

import { ArrowUpIcon } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";

/** The question box: Enter asks, Shift+Enter adds a line. */
export function AskBox({
  label,
  placeholder,
  disabled = false,
  onAsk,
}: {
  label: string;
  placeholder: string;
  disabled?: boolean;
  onAsk: (question: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const id = useId();

  function submit() {
    const text = question.trim();
    if (!text || disabled) return;
    onAsk(text);
    setQuestion("");
  }

  return (
    <form
      className="flex items-end gap-2 rounded-[14px] border border-border-strong bg-surface p-2 focus-within:border-brand"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <textarea
        id={id}
        rows={1}
        value={question}
        maxLength={2000}
        placeholder={placeholder}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        className="field-sizing-content max-h-48 min-h-11 flex-1 resize-none bg-transparent px-2 py-2.5 text-base outline-none placeholder:text-muted-foreground"
      />
      <Button type="submit" size="icon-lg" aria-label="Ask" disabled={disabled || !question.trim()}>
        <ArrowUpIcon aria-hidden="true" />
      </Button>
    </form>
  );
}
