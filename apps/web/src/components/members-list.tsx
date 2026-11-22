"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState } from "react";

import {
  changeRole,
  type MemberSummary,
  removeMember,
  transferOwnership,
} from "@/app/collections-actions";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

const CONNECTION =
  "Can’t reach the server. Check your connection and try again.";
const ROLE_NAMES = {
  owner: "Owner",
  editor: "Editor",
  viewer: "Viewer",
} as const;

/**
 * Who has access to a Collection (GLOSSARY: Member, Role). Everyone sees the list. The Owner
 * changes Roles, removes people, and hands ownership over; anyone else can leave.
 */
export function MembersList({
  collection,
  initialMembers,
  isOwner,
}: {
  collection: { id: string; name: string };
  initialMembers: MemberSummary[];
  isOwner: boolean;
}) {
  const router = useRouter();
  const [members, setMembers] = useState(initialMembers);
  const [announcement, setAnnouncement] = useState("");
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-2 text-left"
    >
      <h3
        ref={heading}
        id={headingId}
        tabIndex={-1}
        className="text-meta font-medium text-muted-foreground"
      >
        People with access
      </h3>
      <ul className="flex flex-col border-t border-border">
        {members.map((member) => (
          <MemberRow
            key={member.user_id}
            member={member}
            collection={collection}
            canManage={isOwner && member.role !== "owner"}
            onRoleChanged={(role) => {
              setMembers((current) =>
                current.map((m) =>
                  m.user_id === member.user_id ? { ...m, role } : m,
                ),
              );
              setAnnouncement(
                `${member.email} is now ${ROLE_NAMES[role].toLowerCase()}.`,
              );
            }}
            onRemoved={() => {
              setMembers((current) =>
                current.filter((m) => m.user_id !== member.user_id),
              );
              setAnnouncement(`${member.email} no longer has access.`);
              heading.current?.focus();
            }}
            onLeft={() => {
              router.push("/");
              router.refresh();
            }}
            onTransferred={() => {
              setAnnouncement(`${member.email} is now the owner.`);
              router.refresh();
            }}
          />
        ))}
      </ul>
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </section>
  );
}

function MemberRow({
  member,
  collection,
  canManage,
  onRoleChanged,
  onRemoved,
  onLeft,
  onTransferred,
}: {
  member: MemberSummary;
  collection: { id: string; name: string };
  canManage: boolean;
  onRoleChanged: (role: "editor" | "viewer") => void;
  onRemoved: () => void;
  onLeft: () => void;
  onTransferred: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const roleId = useId();
  const leaving = member.is_you && member.role !== "owner";

  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border py-2">
      <span className="flex min-w-0 flex-col">
        <span className="truncate" title={member.email}>
          {member.email}
          {member.is_you && (
            <span className="text-muted-foreground"> (you)</span>
          )}
        </span>
        {!canManage && (
          <span className="text-meta text-muted-foreground">
            {ROLE_NAMES[member.role]}
          </span>
        )}
      </span>
      <span className="flex flex-wrap items-center gap-1">
        {canManage && (
          <>
            <label htmlFor={roleId} className="sr-only">
              Role for {member.email}
            </label>
            <select
              id={roleId}
              value={member.role}
              disabled={saving}
              onChange={async (event) => {
                const role = event.target.value as "editor" | "viewer";
                setSaving(true);
                setProblem(null);
                const result = await changeRole(
                  collection.id,
                  member.user_id,
                  role,
                ).catch(() => null);
                setSaving(false);
                if (!result) return setProblem(CONNECTION);
                if (!result.ok) return setProblem(result.message);
                onRoleChanged(role);
              }}
              className="h-8 rounded-md border border-border-strong bg-background px-2 text-meta text-foreground pointer-coarse:h-11"
            >
              <option value="editor">Editor</option>
              <option value="viewer">Viewer</option>
            </select>
            <Confirm
              trigger="Make owner"
              triggerLabel={`Make owner: ${member.email}`}
              title={`Make ${member.email} the owner?`}
              description={`They’ll control ${collection.name}: its people, its name, and deleting it. You’ll stay, as an editor. Only they can undo this.`}
              confirm="Make owner"
              busy="Transferring…"
              onConfirm={() => transferOwnership(collection.id, member.user_id)}
              onDone={onTransferred}
            />
            <Confirm
              trigger="Remove"
              triggerLabel={`Remove ${member.email}`}
              title={`Remove ${member.email}?`}
              description={`They lose access to ${collection.name} from their next question. You can invite them again later.`}
              confirm="Remove"
              busy="Removing…"
              destructive
              onConfirm={() => removeMember(collection.id, member.user_id)}
              onDone={onRemoved}
            />
          </>
        )}
        {leaving && (
          <Confirm
            trigger="Leave collection"
            title={`Leave ${collection.name}?`}
            description="You lose access to its documents. To come back, ask its owner to invite you again."
            confirm="Leave"
            busy="Leaving…"
            destructive
            onConfirm={() => removeMember(collection.id, member.user_id)}
            onDone={onLeft}
          />
        )}
      </span>
      {problem && (
        <p role="alert" className="w-full text-meta text-destructive">
          {problem}
        </p>
      )}
    </li>
  );
}

/** For Editors and Viewers: who has access, and a way to leave. */
export function MemberSettings({
  collection,
  members,
}: {
  collection: { id: string; name: string };
  members: MemberSummary[];
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <div className="flex w-full flex-col gap-3">
      <div data-settings-row className="flex flex-wrap items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((shown) => !shown)}
        >
          People
        </Button>
      </div>
      <div
        id={panelId}
        hidden={!open}
        className="rounded-lg border border-border bg-surface p-4"
      >
        <MembersList
          collection={collection}
          initialMembers={members}
          isOwner={false}
        />
      </div>
    </div>
  );
}

/** A button that asks before doing something to someone's access. */
function Confirm({
  trigger,
  triggerLabel,
  title,
  description,
  confirm,
  busy,
  destructive = false,
  onConfirm,
  onDone,
}: {
  trigger: string;
  /** The accessible name, when the visible text alone doesn't say whom it's about. */
  triggerLabel?: string;
  title: string;
  description: string;
  confirm: string;
  busy: string;
  destructive?: boolean;
  onConfirm: () => Promise<{ ok: true } | { ok: false; message: string }>;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (working) return;
        setOpen(next);
        setProblem(null);
      }}
    >
      <AlertDialogTrigger
        render={<Button variant="ghost" size="sm" aria-label={triggerLabel} />}
      >
        {trigger}
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogTitle>{title}</AlertDialogTitle>
        <AlertDialogDescription>{description}</AlertDialogDescription>
        {problem && (
          <p role="alert" className="text-destructive">
            {problem}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={working}>Cancel</AlertDialogCancel>
          <Button
            variant={destructive ? "destructive" : "default"}
            disabled={working}
            onClick={async () => {
              setWorking(true);
              const result = await onConfirm().catch(() => null);
              setWorking(false);
              if (!result) return setProblem(CONNECTION);
              if (!result.ok) return setProblem(result.message);
              setOpen(false);
              onDone();
            }}
          >
            {working ? busy : confirm}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
