import { FormEvent, useEffect, useState } from "react";
import {
  AlertTriangle,
  Archive,
  Clock,
  FolderPlus,
  Mail,
  Trash2,
  Undo2,
  X
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { ThemeToggle } from "../App";
import {
  createCase,
  deleteCase,
  listCases,
  listTrash,
  permanentlyDeleteCase,
  restoreCase,
  updateCase
} from "../api/client";
import type { CaseRecord } from "../types";

export function CaseListPage() {
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [trash, setTrash] = useState<CaseRecord[]>([]);
  const [showTrash, setShowTrash] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pendingDelete, setPendingDelete] = useState<CaseRecord | null>(null);
  const [renameCase, setRenameCase] = useState<CaseRecord | null>(null);
  const navigate = useNavigate();

  function goHome() {
    setShowTrash(false);
    navigate("/");
  }

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const [active, deleted] = await Promise.all([listCases(), listTrash()]);
      setCases(active);
      setTrash(deleted);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load cases");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const created = await createCase(name.trim(), browserTz);
    navigate(`/cases/${created.public_id}`);
  }

  async function onTrash(caseRecord: CaseRecord) {
    await deleteCase(caseRecord.id);
    await refresh();
  }

  async function onRestore(caseId: number) {
    await restoreCase(caseId);
    await refresh();
  }

  async function onConfirmPermanentDelete() {
    if (!pendingDelete) return;
    await permanentlyDeleteCase(pendingDelete.id, pendingDelete.name);
    setPendingDelete(null);
    await refresh();
  }

  async function onRename(caseId: number, nextName: string) {
    await updateCase(caseId, { name: nextName });
    setRenameCase(null);
    await refresh();
  }

  return (
    <section className="case-index">
      <div className="masthead">
        <div>
          <p className="eyebrow">Local chronology workspace</p>
          <h1>
            <button type="button" className="home-title" onClick={goHome}>
              Chronology
            </button>
          </h1>
        </div>
        <div className="status-strip">
          <button type="button" className="chip-button" onClick={goHome}>
            <Archive size={16} /> {cases.length} matters
          </button>
          <span>
            <Mail size={16} /> localhost only
          </span>
          <button
            type="button"
            className={`chip-button ${showTrash ? "active" : ""}`}
            onClick={() => setShowTrash((value) => !value)}
          >
            <Trash2 size={16} /> Trash {trash.length > 0 && `(${trash.length})`}
          </button>
          <ThemeToggle />
        </div>
      </div>

      <form className="new-case-bar" onSubmit={onSubmit}>
        <FolderPlus size={20} />
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="New matter name"
        />
        <button type="submit">Create</button>
      </form>

      {error && <div className="notice error">{error}</div>}
      {loading && <div className="notice">Loading matters...</div>}

      {showTrash ? (
        <TrashView
          trash={trash}
          onRestore={onRestore}
          onRequestDelete={(caseRecord) => setPendingDelete(caseRecord)}
        />
      ) : (
        <div className="case-grid">
          {!loading && cases.length === 0 && (
            <div className="empty-state">
              <h2>No matters yet</h2>
              <p>Create a matter above to start building a chronology.</p>
            </div>
          )}
          {cases.map((item) => (
            <article className="case-row" key={item.id}>
              <Link to={`/cases/${item.public_id}`} className="case-row-main">
                <div className="case-mark">{item.name.slice(0, 2).toUpperCase()}</div>
                <div>
                  <h2
                    title="Right-click to rename"
                    onContextMenu={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      setRenameCase(item);
                    }}
                  >
                    {item.name}
                  </h2>
                  <p>
                    <Clock size={14} /> Updated {formatDate(item.updated_at)}
                  </p>
                </div>
              </Link>
              <div className="case-row-meta">
                <strong>{item.email_count}</strong>
                <span>emails</span>
              </div>
              <button
                className="icon-button"
                title="Move to trash"
                onClick={() => void onTrash(item)}
                type="button"
              >
                <Trash2 size={18} />
              </button>
            </article>
          ))}
        </div>
      )}

      {pendingDelete && (
        <PermanentDeleteDialog
          caseRecord={pendingDelete}
          onCancel={() => setPendingDelete(null)}
          onConfirm={onConfirmPermanentDelete}
        />
      )}
      {renameCase && (
        <RenameDialog
          caseRecord={renameCase}
          onCancel={() => setRenameCase(null)}
          onConfirm={onRename}
        />
      )}
    </section>
  );
}

type TrashViewProps = {
  trash: CaseRecord[];
  onRestore: (caseId: number) => void;
  onRequestDelete: (caseRecord: CaseRecord) => void;
};

function TrashView({ trash, onRestore, onRequestDelete }: TrashViewProps) {
  if (trash.length === 0) {
    return (
      <div className="empty-state">
        <h2>Trash is empty</h2>
        <p>Matters you move to trash can be recovered here until you permanently delete them.</p>
      </div>
    );
  }
  return (
    <div className="case-grid">
      {trash.map((item) => (
        <article className="case-row trashed" key={item.id}>
          <div className="case-row-main">
            <div className="case-mark trashed">
              <Trash2 size={18} />
            </div>
            <div>
              <h2>{item.name}</h2>
              <p>
                <Clock size={14} /> Trashed {item.deleted_at ? formatDate(item.deleted_at) : ""}
              </p>
            </div>
          </div>
          <div className="case-row-meta">
            <strong>{item.email_count}</strong>
            <span>emails kept</span>
          </div>
          <div className="trash-actions">
            <button
              className="ghost-button"
              type="button"
              onClick={() => onRestore(item.id)}
            >
              <Undo2 size={16} /> Recover
            </button>
            <button
              className="danger-button"
              type="button"
              onClick={() => onRequestDelete(item)}
            >
              <Trash2 size={16} /> Delete forever
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

type DialogProps = {
  caseRecord: CaseRecord;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
};

function PermanentDeleteDialog({ caseRecord, onCancel, onConfirm }: DialogProps) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const matches = typed.trim() === caseRecord.name.trim();

  async function confirm() {
    if (!matches || busy) return;
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dialog-scrim" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <div className="dialog-icon">
            <AlertTriangle size={20} />
          </div>
          <button className="icon-button" type="button" onClick={onCancel} title="Cancel">
            <X size={18} />
          </button>
        </header>
        <h2>Permanently delete this matter?</h2>
        <p>
          This removes <strong>{caseRecord.name}</strong> and all{" "}
          {caseRecord.email_count} of its emails, attachments, and edit history. This
          cannot be undone.
        </p>
        <label className="dialog-field">
          <span>
            Type <b>{caseRecord.name}</b> to confirm
          </span>
          <input
            autoFocus
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder={caseRecord.name}
            onKeyDown={(event) => {
              if (event.key === "Enter") void confirm();
            }}
          />
        </label>
        <div className="dialog-actions">
          <button className="ghost-button" type="button" onClick={onCancel}>
            Cancel
          </button>
          <button
            className="danger-button"
            type="button"
            disabled={!matches || busy}
            onClick={() => void confirm()}
          >
            <Trash2 size={16} />
            {busy ? "Deleting..." : "Delete forever"}
          </button>
        </div>
      </div>
    </div>
  );
}

type RenameDialogProps = {
  caseRecord: CaseRecord;
  onCancel: () => void;
  onConfirm: (caseId: number, nextName: string) => Promise<void>;
};

function RenameDialog({ caseRecord, onCancel, onConfirm }: RenameDialogProps) {
  const [value, setValue] = useState(caseRecord.name);
  const [busy, setBusy] = useState(false);
  const nextName = value.trim();
  const changed = nextName && nextName !== caseRecord.name.trim();

  async function confirm() {
    if (!changed || busy) return;
    setBusy(true);
    try {
      await onConfirm(caseRecord.id, nextName);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dialog-scrim" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <p className="eyebrow">Rename matter</p>
            <h2>{caseRecord.name}</h2>
          </div>
          <button className="icon-button" type="button" onClick={onCancel} title="Cancel">
            <X size={18} />
          </button>
        </header>
        <label className="dialog-field">
          <span>Project name</span>
          <input
            autoFocus
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void confirm();
              if (event.key === "Escape") onCancel();
            }}
          />
        </label>
        <div className="dialog-actions">
          <button className="ghost-button" type="button" onClick={onCancel}>
            Cancel
          </button>
          <button
            className="save-button"
            type="button"
            disabled={!changed || busy}
            onClick={() => void confirm()}
          >
            {busy ? "Renaming..." : "Rename"}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid date";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}
