import { FormEvent, useEffect, useState } from "react";
import { Plus, Save, X } from "lucide-react";
import type { EmailCreate, EmailRecord } from "../types";
import { DATE_INPUT_HINT, DATE_INPUT_PLACEHOLDER, parseDateInput } from "../utils/dateInput";

type Props = {
  open: boolean;
  onClose: () => void;
  onCreate: (payload: EmailCreate) => Promise<EmailRecord>;
};

export function ManualEmailDrawer({ open, onClose, onCreate }: Props) {
  const [fromAddr, setFromAddr] = useState("");
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [dateRaw, setDateRaw] = useState("");
  const [subject, setSubject] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [notes, setNotes] = useState("");
  const [important, setImportant] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (open) return;
    setFromAddr("");
    setTo("");
    setCc("");
    setDateRaw("");
    setSubject("");
    setBodyText("");
    setNotes("");
    setImportant(false);
    setError("");
    setSaving(false);
  }, [open]);

  if (!open) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    const parsedDate = parseDateInput(dateRaw);
    if (!parsedDate.ok) {
      setError(parsedDate.error);
      return;
    }
    setSaving(true);
    try {
      await onCreate({
        from_addr: fromAddr,
        to: splitList(to),
        cc: splitList(cc),
        date_raw: parsedDate.value,
        subject,
        body_text: bodyText,
        notes,
        important
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add email");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="drawer-scrim" onClick={onClose}>
      <aside className="email-drawer" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <p className="eyebrow">Manual entry</p>
            <h2>Add email</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} title="Close">
            <X size={18} />
          </button>
        </header>

        <form onSubmit={submit} className="drawer-form">
          {error && <div className="notice error">{error}</div>}
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
              value={dateRaw}
              onChange={(event) => setDateRaw(event.target.value)}
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
          <label>
            <span>Notes</span>
            <textarea
              className="compact-textarea"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </label>
          <label className="checkbox-field">
            <input
              checked={important}
              type="checkbox"
              onChange={(event) => setImportant(event.target.checked)}
            />
            <span>Important</span>
          </label>

          <button className="save-button" type="submit" disabled={saving}>
            {saving ? <Save size={17} /> : <Plus size={17} />}
            {saving ? "Adding" : "Add email"}
          </button>
        </form>
      </aside>
    </div>
  );
}

function splitList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
