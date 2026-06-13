import { FormEvent, useEffect, useState } from "react";
import { ExternalLink, Save, X } from "lucide-react";
import type { EmailRecord, EmailUpdate } from "../types";
import {
  DATE_INPUT_HINT,
  DATE_INPUT_PLACEHOLDER,
  formatDateInput,
  parseDateInput
} from "../utils/dateInput";

type Props = {
  email: EmailRecord | null;
  onClose: () => void;
  onSave: (emailId: number, update: EmailUpdate) => Promise<void>;
  timeZone?: string;
};

export function EmailDrawer({ email, onClose, onSave, timeZone }: Props) {
  const [fromAddr, setFromAddr] = useState("");
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [dateInput, setDateInput] = useState("");
  const [subject, setSubject] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!email) return;
    setError("");
    setFromAddr(email.from_addr);
    setTo(email.to.join(", "));
    setCc(email.cc.join(", "));
    // Show the stored instant in the matter timezone, in the enforced input
    // format, so editing other fields and saving round-trips the date.
    setDateInput(formatDateInput(email.date_utc, timeZone));
    setSubject(email.subject);
    setBodyText(email.body_text);
  }, [email, timeZone]);

  useEffect(() => {
    if (!email) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [email, onClose]);

  if (!email) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!email) return;
    setError("");
    const parsedDate = parseDateInput(dateInput);
    if (!parsedDate.ok) {
      setError(parsedDate.error);
      return;
    }
    setSaving(true);
    try {
      await onSave(email.id, {
        from_addr: fromAddr,
        to: splitList(to),
        cc: splitList(cc),
        date_utc: parsedDate.value,
        subject,
        body_text: bodyText
      });
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="drawer-scrim" onClick={onClose}>
      <aside className="email-drawer" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <p className="eyebrow">Edit email</p>
            <h2>{email.subject}</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} title="Close">
            <X size={18} />
          </button>
        </header>

        <form onSubmit={submit} className="drawer-form">
          {error && <div className="drawer-error">{error}</div>}
          <label>
            <span>From</span>
            <input value={fromAddr} onChange={(event) => setFromAddr(event.target.value)} />
          </label>
          <label>
            <span>To</span>
            <input value={to} onChange={(event) => setTo(event.target.value)} />
          </label>
          <label>
            <span>Cc</span>
            <input value={cc} onChange={(event) => setCc(event.target.value)} />
          </label>
          <label>
            <span>Date</span>
            <input
              value={dateInput}
              onChange={(event) => setDateInput(event.target.value)}
              placeholder={DATE_INPUT_PLACEHOLDER}
            />
            <small className="field-hint">{DATE_INPUT_HINT}</small>
          </label>
          <label>
            <span>Subject</span>
            <input value={subject} onChange={(event) => setSubject(event.target.value)} />
          </label>
          <label>
            <span>Body text</span>
            <textarea value={bodyText} onChange={(event) => setBodyText(event.target.value)} />
          </label>

          {email.flags.length > 0 && (
            <div className="flag-box">
              {email.flags.map((flag) => (
                <span key={flag}>{flag}</span>
              ))}
            </div>
          )}

          {email.attachments.length > 0 && (
            <div className="attachment-box">
              <h3>Attachments</h3>
              {email.attachments.map((attachment) => (
                <a key={attachment.id} href={`/api/attachments/${attachment.id}`}>
                  <ExternalLink size={14} />
                  {attachment.filename}
                </a>
              ))}
            </div>
          )}

          <button className="save-button" type="submit" disabled={saving}>
            <Save size={17} />
            {saving ? "Saving" : "Save changes"}
          </button>
        </form>
      </aside>
    </div>
  );
}

function readErrorMessage(err: unknown) {
  if (!(err instanceof Error)) return "Changes could not be saved";
  try {
    const parsed = JSON.parse(err.message) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // Use the original message when the response is not JSON.
  }
  return err.message || "Changes could not be saved";
}

function splitList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
