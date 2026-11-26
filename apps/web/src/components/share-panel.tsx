"use client";

import { useEffect, useId, useRef, useState } from "react";

import {
  type InviteSummary,
  inviteToCollection,
  revokeInvite,
} from "@/app/collections-actions";
import { Button } from "@/components/ui/button";
import { formatLocalDate } from "@/lib/dates";
import { useInBrowser } from "@/lib/use-in-browser";

const CONNECTION =
  "Can’t reach the server. Check your connection and try again.";
const ROLES: { value: InviteSummary["role"]; label: string; hint: string }[] = [
  { value: "viewer", label: "Viewer", hint: "can ask questions" },
  {
    value: "editor",
    label: "Editor",
    hint: "can also manage documents",
  },
];

/** Where an invite's link leads (FLOWS › Share): signing in there as the invited address. */
export function inviteLink(id: string): string {
  return `${window.location.origin}/invites/${id}`;
}

/**
 * The Owner invites people by email (GLOSSARY: Invite). Docent sends no email: the Owner copies
 * the link and sends it however they like. Waiting invites can be copied again or cancelled.
 */
export function SharePanel({
  collectionId,
  initialInvites,
}: {
  collectionId: string;
  initialInvites: InviteSummary[];
}) {
  const [invites, setInvites] = useState(initialInvites);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<InviteSummary["role"]>("viewer");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [sent, setSent] = useState<InviteSummary | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const emailId = useId();
  const roleId = useId();
  const problemId = useId();
  const headingId = useId();
  const emailInput = useRef<HTMLInputElement>(null);
  const linkInput = useRef<HTMLInputElement>(null);

  // A new invite's link takes focus: the Invite button it came from is disabled once the
  // address is cleared, and the link is what to do next.
  useEffect(() => {
    if (sent) linkInput.current?.focus();
  }, [sent]);

  const copy = async (invite: InviteSummary) => {
    try {
      await navigator.clipboard.writeText(inviteLink(invite.id));
      setAnnouncement(`Link for ${invite.email} copied.`);
    } catch {
      setAnnouncement("Couldn’t copy. Select the link and copy it yourself.");
    }
  };

  return (
    <section
      aria-labelledby={headingId}
      className="flex w-full flex-col gap-4 self-stretch rounded-lg border border-border bg-surface p-4 text-left"
    >
      <div className="flex flex-col gap-1">
        <h2 id={headingId} className="font-sans text-ui font-semibold">
          Invite people
        </h2>
        <p className="text-meta text-text-secondary text-pretty">
          Docent doesn’t send emails: copy the link and send it yourself. It
          works only for the address you invite, and signing in with that
          address is enough, even without the link. Once someone accepts,
          they’re a member of this collection.
        </p>
      </div>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!email.trim()) return;
          setSending(true);
          setProblem(null);
          const result = await inviteToCollection(
            collectionId,
            email,
            role,
          ).catch(() => null);
          setSending(false);
          if (!result) return setProblem(CONNECTION);
          if (!result.ok) return setProblem(result.message);
          setInvites((current) => [
            result.value,
            ...current.filter((i) => i.id !== result.value.id),
          ]);
          setSent(result.value);
          setEmail("");
          setAnnouncement(
            `${result.value.email} invited. Copy the link to send it.`,
          );
        }}
      >
        <span className="flex min-w-0 flex-1 basis-56 flex-col gap-1">
          <label htmlFor={emailId} className="text-meta text-muted-foreground">
            Email address
          </label>
          <input
            ref={emailInput}
            id={emailId}
            type="email"
            required
            autoComplete="off"
            value={email}
            aria-invalid={problem ? true : undefined}
            aria-describedby={problem ? problemId : undefined}
            onChange={(event) => setEmail(event.target.value)}
            className="h-9 rounded-md border border-border-strong bg-background px-2 text-foreground pointer-coarse:h-11"
          />
        </span>
        <span className="flex min-w-0 flex-1 basis-56 flex-col gap-1">
          <label htmlFor={roleId} className="text-meta text-muted-foreground">
            Role
          </label>
          <select
            id={roleId}
            value={role}
            onChange={(event) =>
              setRole(event.target.value as InviteSummary["role"])
            }
            className="h-9 w-full min-w-0 rounded-md border border-border-strong bg-background px-2 text-foreground pointer-coarse:h-11"
          >
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label} ({r.hint})
              </option>
            ))}
          </select>
        </span>
        <Button type="submit" disabled={sending || !email.trim()}>
          {sending ? "Inviting…" : "Invite"}
        </Button>
        {problem && (
          <p
            id={problemId}
            role="alert"
            className="w-full text-meta text-destructive"
          >
            {problem}
          </p>
        )}
      </form>

      {sent && (
        <div className="flex flex-col gap-2 rounded-md bg-brand-subtle p-3 text-brand-subtle-text">
          <p className="text-meta">
            Send this link to {sent.email}. It works until{" "}
            {formatLocalDate(sent.expires_at)}.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={linkInput}
              readOnly
              aria-label={`Invite link for ${sent.email}`}
              value={inviteLink(sent.id)}
              onFocus={(event) => event.currentTarget.select()}
              className="h-9 min-w-0 flex-1 basis-56 rounded-md border border-border-strong bg-background px-2 text-meta text-foreground"
            />
            <Button size="sm" onClick={() => void copy(sent)}>
              Copy link
            </Button>
          </div>
        </div>
      )}

      {invites.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-meta font-medium text-muted-foreground">
            Waiting to accept
          </h3>
          <ul className="flex flex-col border-t border-border">
            {invites.map((invite) => (
              <WaitingInvite
                key={invite.id}
                invite={invite}
                onCopy={() => void copy(invite)}
                onCancelled={() => {
                  setInvites((current) =>
                    current.filter((i) => i.id !== invite.id),
                  );
                  if (sent?.id === invite.id) setSent(null);
                  setAnnouncement(
                    `The invite for ${invite.email} was cancelled.`,
                  );
                  emailInput.current?.focus();
                }}
              />
            ))}
          </ul>
        </div>
      )}
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </section>
  );
}

function WaitingInvite({
  invite,
  onCopy,
  onCancelled,
}: {
  invite: InviteSummary;
  onCopy: () => void;
  onCancelled: () => void;
}) {
  const [cancelling, setCancelling] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const role = ROLES.find((r) => r.value === invite.role)?.label ?? invite.role;
  // In the reader's time zone, known only in the browser.
  const until = useInBrowser() ? formatLocalDate(invite.expires_at) : "…";
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border py-2">
      <span className="flex min-w-0 flex-col">
        <span className="truncate" title={invite.email}>
          {invite.email}
        </span>
        <span className="text-meta text-muted-foreground">
          {role} · link works until {until}
        </span>
      </span>
      <span className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          aria-label={`Copy link for ${invite.email}`}
          onClick={onCopy}
        >
          Copy link
        </Button>
        <Button
          variant="ghost"
          size="sm"
          aria-label={`Cancel invite for ${invite.email}`}
          disabled={cancelling}
          onClick={async () => {
            setCancelling(true);
            const result = await revokeInvite(invite.id).catch(() => null);
            setCancelling(false);
            if (!result) return setProblem(CONNECTION);
            if (!result.ok) return setProblem(result.message);
            onCancelled();
          }}
        >
          {cancelling ? "Cancelling…" : "Cancel invite"}
        </Button>
      </span>
      {problem && (
        <p role="alert" className="w-full text-meta text-destructive">
          {problem}
        </p>
      )}
    </li>
  );
}
