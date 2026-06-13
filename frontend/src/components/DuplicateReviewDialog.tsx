import { CheckCircle2, Copy, X } from "lucide-react";
import type { DuplicateCandidate, EmailRecord } from "../types";

export function DuplicateReviewDialog({
  activeEmail,
  candidates,
  loading,
  savingId,
  onClose,
  onMark,
  onDissimilar,
  timeZone
}: {
  activeEmail: EmailRecord | null;
  candidates: DuplicateCandidate[];
  loading: boolean;
  savingId: number | null;
  onClose: () => void;
  onMark: (candidate: DuplicateCandidate, duplicateEmailId: number) => void;
  onDissimilar: (candidate: DuplicateCandidate) => void;
  timeZone?: string;
}) {
  if (!activeEmail) return null;

  return (
    <div
      className="duplicate-dialog-scrim"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="duplicate-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Review suspected duplicates"
      >
        <header>
          <div>
            <p className="eyebrow">Duplicate Review</p>
            <h2>{activeEmail.subject || "(no subject)"}</h2>
            <span>
              {loading
                ? "Checking candidates..."
                : `${candidates.length} pending ${candidates.length === 1 ? "candidate" : "candidates"}`}
            </span>
          </div>
          <button className="icon-button" type="button" title="Close" onClick={onClose}>
            <X size={17} />
          </button>
        </header>

        {loading ? (
          <div className="duplicate-empty">Loading suspected duplicates...</div>
        ) : candidates.length === 0 ? (
          <div className="duplicate-empty">
            <CheckCircle2 size={20} />
            <p>No pending suspected duplicates for this email.</p>
          </div>
        ) : (
          <div className="duplicate-candidate-list">
            {candidates.map((candidate) => {
              const other = otherDuplicateEmail(candidate, activeEmail.id);
              if (!other) return null;
              const saving = savingId === candidate.id;
              return (
                <article className="duplicate-candidate" key={candidate.id}>
                  <div className="duplicate-candidate-header">
                    <div>
                      <strong>{formatDuplicateScore(candidate.score)} match</strong>
                      <span>{candidate.reasons.map((reason) => reason.label).join(" | ")}</span>
                    </div>
                    <Copy size={18} />
                  </div>
                  <div className="duplicate-compare">
                    <DuplicateEmailPreview
                      email={activeEmail}
                      label="Current"
                      timeZone={timeZone}
                    />
                    <DuplicateEmailPreview
                      email={other}
                      label="Candidate"
                      timeZone={timeZone}
                    />
                  </div>
                  <div className="duplicate-actions">
                    <button
                      className="ghost-button"
                      type="button"
                      disabled={saving}
                      onClick={() => onDissimilar(candidate)}
                    >
                      Dissimilar
                    </button>
                    <button
                      className="ghost-button"
                      type="button"
                      disabled={saving}
                      title="Keep the candidate and mark the current email as the duplicate"
                      onClick={() => onMark(candidate, activeEmail.id)}
                    >
                      Mark current duplicate
                    </button>
                    <button
                      className="save-button"
                      type="button"
                      disabled={saving}
                      title="Keep the current email and mark the candidate as the duplicate"
                      onClick={() => onMark(candidate, other.id)}
                    >
                      {saving ? "Saving..." : "Mark candidate duplicate"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

export function otherDuplicateEmail(candidate: DuplicateCandidate, activeEmailId: number) {
  if (candidate.email_a_id === activeEmailId) return candidate.email_b ?? null;
  if (candidate.email_b_id === activeEmailId) return candidate.email_a ?? null;
  return null;
}

function DuplicateEmailPreview({
  email,
  label,
  timeZone
}: {
  email: EmailRecord;
  label: string;
  timeZone?: string;
}) {
  return (
    <div className="duplicate-preview">
      <div>
        <span>{label}</span>
        <strong>{formatDeletedDate(email.date_utc)}</strong>
      </div>
      <h3>{email.subject || "(no subject)"}</h3>
      <dl>
        <div>
          <dt>From</dt>
          <dd>{email.from_addr || "Unknown sender"}</dd>
        </div>
        <div>
          <dt>To</dt>
          <dd>{formatRecipients(email.to)}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>{email.source_file_display}</dd>
        </div>
        {email.source_sha256 && (
          <div>
            <dt>SHA</dt>
            <dd>{email.source_sha256.slice(0, 12)}</dd>
          </div>
        )}
      </dl>
      <p>{compactSnippet(email.body_text)}</p>
      <small>{formatExportDate(email.date_utc, timeZone)}</small>
    </div>
  );
}

function formatDuplicateScore(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatRecipients(values: string[]) {
  if (!values.length) return "No recipients";
  return values.join(", ");
}

function compactSnippet(value: string) {
  const text = value.replace(/\s+/g, " ").trim();
  if (!text) return "No plain-text body captured.";
  return text.length > 160 ? `${text.slice(0, 160).trimEnd()}...` : text;
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

function formatExportDate(value?: string | null, timeZone?: string) {
  const date = validDate(value);
  if (!date) return value ? "Invalid date" : "";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone
  }).format(date);
}

function validDate(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
