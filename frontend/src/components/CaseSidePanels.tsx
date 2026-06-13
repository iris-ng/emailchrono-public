import { useState } from "react";
import { History, Trash2, Undo2 } from "lucide-react";
import type { AuditEvent, EmailRecord } from "../types";

export function EmailTrashPanel({
  trash,
  onRestore
}: {
  trash: EmailRecord[];
  onRestore: (emailId: number) => void;
}) {
  if (!trash.length) {
    return (
      <div className="email-trash-panel empty">
        <Trash2 size={17} />
        <p>No recoverable emails in trash.</p>
      </div>
    );
  }

  return (
    <div className="email-trash-panel">
      <header>
        <div>
          <h2>Recoverable emails</h2>
          <span>Available for 30 days after deletion.</span>
        </div>
      </header>
      <div className="email-trash-list">
        {trash.map((email) => (
          <article className="email-trash-item" key={email.id}>
            <div>
              <h3>{email.subject || "(no subject)"}</h3>
              <p>{email.from_addr || "Unknown sender"}</p>
              <span>
                Trashed {formatDeletedDate(email.deleted_at)} - {trashDaysRemaining(email.deleted_at)} left
              </span>
            </div>
            <button
              className="ghost-button"
              type="button"
              title="Restore email"
              onClick={() => onRestore(email.id)}
            >
              <Undo2 size={15} /> Restore
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}

export function AuditTrailPanel({
  events,
  onJumpToEmail
}: {
  events: AuditEvent[];
  onJumpToEmail: (emailId: number) => void;
}) {
  if (!events.length) {
    return (
      <div className="audit-panel empty">
        <History size={17} />
        <p>No audit events yet.</p>
      </div>
    );
  }

  return (
    <div className="audit-panel">
      <header>
        <div>
          <h2>Recent activity</h2>
          <span>Append-only, hash-linked events.</span>
        </div>
      </header>
      <div className="audit-list">
        {events.map((event) => (
          <AuditItem key={event.id} event={event} onJumpToEmail={onJumpToEmail} />
        ))}
      </div>
    </div>
  );
}

function AuditItem({
  event,
  onJumpToEmail
}: {
  event: AuditEvent;
  onJumpToEmail: (emailId: number) => void;
}) {
  const [open, setOpen] = useState(false);

  if (event.action !== "ingest.completed") {
    return (
      <article className="audit-item">
        <div>
          <strong>{formatAuditAction(event.action)}</strong>
          <span>{formatDeletedDate(event.created_at)}</span>
        </div>
        <p>{auditSummary(event)}</p>
        <small title={event.event_hash}>hash {event.event_hash.slice(0, 12)}</small>
      </article>
    );
  }

  const meta = event.metadata || {};
  const totalFiles = numberValue(meta.total_files);
  const failed = numberValue(meta.failed_files);
  const emailCount = numberValue(meta.email_count);
  const counts =
    meta.counts && typeof meta.counts === "object" ? (meta.counts as Record<string, number>) : {};
  const fileNames = Array.isArray(meta.file_names) ? (meta.file_names as string[]) : [];
  const emailIds = Array.isArray(meta.email_ids) ? (meta.email_ids as number[]) : [];
  const tagNames = Array.isArray(meta.tag_names) ? (meta.tag_names as string[]) : [];
  const breakdown = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([kind, count]) => `${count} ${kind}`)
    .join(", ");

  return (
    <article className="audit-item upload">
      <div>
        <strong>Upload</strong>
        <span>{formatDeletedDate(event.created_at)}</span>
      </div>
      <p>
        {totalFiles} {totalFiles === 1 ? "file" : "files"} {"\u2192"} {emailCount}{" "}
        {emailCount === 1 ? "email" : "emails"}
        {breakdown ? ` (${breakdown})` : ""}
        {failed > 0 ? ` \u00b7 ${failed} failed` : ""}
      </p>
      {(fileNames.length > 0 || emailIds.length > 0) && (
        <button type="button" className="audit-expand" onClick={() => setOpen((value) => !value)}>
          {open ? "Hide details" : "Show details"}
        </button>
      )}
      {open && (
        <div className="audit-upload-detail">
          {fileNames.length > 0 && (
            <>
              <span className="audit-detail-label">Files</span>
              <ul>
                {fileNames.map((name, index) => (
                  <li key={index}>{name}</li>
                ))}
              </ul>
            </>
          )}
          {tagNames.length > 0 && (
            <>
              <span className="audit-detail-label">Tags</span>
              <div className="audit-tag-list">{tagNames.join(", ")}</div>
            </>
          )}
          {emailIds.length > 0 && (
            <>
              <span className="audit-detail-label">Emails</span>
              <div className="audit-email-chips">
                {emailIds.map((id) => (
                  <button type="button" key={id} onClick={() => onJumpToEmail(id)}>
                    #{id}
                  </button>
                ))}
              </div>
            </>
          )}
          <small title={event.event_hash}>hash {event.event_hash.slice(0, 12)}</small>
        </div>
      )}
    </article>
  );
}

function formatAuditAction(value: string) {
  return value
    .replace(/\./g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function auditSummary(event: AuditEvent) {
  const metadata = event.metadata || {};
  const after = event.after || {};
  const before = event.before || {};
  const subject = stringValue(after.subject) || stringValue(before.subject) || stringValue(metadata.subject);
  if (subject) return subject;
  const fields = Array.isArray(metadata.fields) ? metadata.fields.join(", ") : "";
  if (fields) return `Fields: ${fields}`;
  const entityId = event.entity_id ? ` #${event.entity_id}` : "";
  return `${event.entity_type}${entityId}`;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function formatDeletedDate(value?: string | null) {
  const date = validDate(value);
  if (!date) return value ? "Invalid date" : "unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function trashDaysRemaining(value?: string | null) {
  if (!value) return "30 days";
  const deleted = validDate(value)?.getTime();
  if (deleted === undefined) return "30 days";
  const expires = deleted + 30 * 24 * 60 * 60 * 1000;
  const days = Math.max(0, Math.ceil((expires - Date.now()) / (24 * 60 * 60 * 1000)));
  return days === 1 ? "1 day" : `${days} days`;
}

function validDate(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
