import { useEffect, useRef, useState, type DragEvent, type PointerEvent } from "react";
import { AlertTriangle, GripVertical, Save, X } from "lucide-react";
import type { EmailRecord } from "../types";

type DropPosition = "before" | "after";

type Props = {
  emails: EmailRecord[];
  activeEmail: EmailRecord | null;
  timeZone?: string;
  onClose: () => void;
  onSave: (emailIds: number[]) => Promise<void>;
  onScrollToEmail?: (emailId: number) => void;
};

const WIDTH_STORAGE_KEY = "emailchrono.chainPanelWidth";
const MIN_WIDTH = 380;
const MAX_WIDTH = 920;
const DEFAULT_WIDTH = 680;

function clampWidth(value: number) {
  const ceiling = Math.min(MAX_WIDTH, typeof window !== "undefined" ? window.innerWidth : MAX_WIDTH);
  return Math.max(MIN_WIDTH, Math.min(value, ceiling));
}

function readStoredWidth() {
  try {
    const raw = window.localStorage.getItem(WIDTH_STORAGE_KEY);
    if (!raw) return DEFAULT_WIDTH;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) ? clampWidth(parsed) : DEFAULT_WIDTH;
  } catch {
    return DEFAULT_WIDTH;
  }
}

export function ChainOrderPanel({ emails, activeEmail, timeZone, onClose, onSave, onScrollToEmail }: Props) {
  const [items, setItems] = useState<EmailRecord[]>(emails);
  const [draggedId, setDraggedId] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<{ id: number; position: DropPosition } | null>(null);
  const [saving, setSaving] = useState(false);
  const [width, setWidth] = useState<number>(() => readStoredWidth());
  const resizeStart = useRef<{ x: number; width: number } | null>(null);

  useEffect(() => {
    setItems(emails);
  }, [emails]);

  useEffect(() => {
    if (!activeEmail) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [activeEmail, onClose]);

  if (!activeEmail) return null;

  async function saveOrder() {
    setSaving(true);
    try {
      await onSave(items.map((email) => email.id));
    } finally {
      setSaving(false);
    }
  }

  function moveEmail(sourceId: number, targetId: number, position: DropPosition) {
    if (sourceId === targetId) {
      setDropTarget(null);
      return;
    }
    setItems((current) => {
      const sourceIndex = current.findIndex((email) => email.id === sourceId);
      const targetIndex = current.findIndex((email) => email.id === targetId);
      if (sourceIndex < 0 || targetIndex < 0) return current;
      const next = [...current];
      const [moved] = next.splice(sourceIndex, 1);
      const adjustedTargetIndex = next.findIndex((email) => email.id === targetId);
      const insertIndex = position === "after" ? adjustedTargetIndex + 1 : adjustedTargetIndex;
      next.splice(insertIndex, 0, moved);
      return next;
    });
    setDropTarget(null);
  }

  function startResize(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    resizeStart.current = { x: event.clientX, width };
    event.currentTarget.setPointerCapture(event.pointerId);
    document.body.classList.add("chain-resizing");
  }

  function onResizeMove(event: PointerEvent<HTMLDivElement>) {
    if (!resizeStart.current) return;
    // Panel is right-docked, so dragging left (smaller clientX) grows it.
    const delta = resizeStart.current.x - event.clientX;
    setWidth(clampWidth(resizeStart.current.width + delta));
  }

  function endResize(event: PointerEvent<HTMLDivElement>) {
    if (!resizeStart.current) return;
    resizeStart.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    document.body.classList.remove("chain-resizing");
    try {
      window.localStorage.setItem(WIDTH_STORAGE_KEY, String(Math.round(width)));
    } catch {
      // ignore persistence failures (private mode, etc.)
    }
  }

  return (
    <div className="chain-drawer-scrim">
      <aside
        className="chain-panel"
        style={{ width }}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          className="chain-panel-resizer"
          role="separator"
          aria-orientation="vertical"
          title="Drag to resize"
          onPointerDown={startResize}
          onPointerMove={onResizeMove}
          onPointerUp={endResize}
          onPointerCancel={endResize}
        />
        <header>
          <div>
            <p className="eyebrow">Chain order</p>
            <h2>{stripSubjectPrefix(activeEmail.subject)}</h2>
            <span>{items.length} in chain</span>
          </div>
          <button className="icon-button" type="button" title="Close" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <div className="chain-panel-list">
          {items.map((email, index) => (
            <article
              className={[
                "chain-order-card",
                draggedId === email.id ? "dragging" : "",
                dropTarget?.id === email.id ? `drop-${dropTarget.position}` : ""
              ]
                .filter(Boolean)
                .join(" ")}
              draggable
              key={email.id}
              onDragStart={(event) => {
                setDraggedId(email.id);
                setDropTarget(null);
                event.dataTransfer.effectAllowed = "move";
              }}
              onDragEnd={() => {
                setDraggedId(null);
                setDropTarget(null);
              }}
              onDragLeave={(event) => {
                const nextTarget = event.relatedTarget;
                if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
                if (dropTarget?.id === email.id) setDropTarget(null);
              }}
              onDragOver={(event) => {
                event.preventDefault();
                if (draggedId === null || draggedId === email.id) {
                  setDropTarget(null);
                  return;
                }
                setDropTarget({ id: email.id, position: dropPositionForEvent(event) });
              }}
              onDrop={(event) => {
                event.preventDefault();
                if (draggedId === null) return;
                const position =
                  dropTarget?.id === email.id ? dropTarget.position : dropPositionForEvent(event);
                moveEmail(draggedId, email.id, position);
              }}
            >
              <button
                className="drag-handle"
                type="button"
                title="Drag to reorder"
                draggable
                onDragStart={(event) => {
                  setDraggedId(email.id);
                  setDropTarget(null);
                  event.dataTransfer.effectAllowed = "move";
                }}
              >
                <GripVertical size={17} />
              </button>
              <div className="chain-order-index">{index + 1}</div>
              <div
                className={`chain-order-main${onScrollToEmail ? " chain-order-clickable" : ""}`}
                role={onScrollToEmail ? "button" : undefined}
                tabIndex={onScrollToEmail ? 0 : undefined}
                title={onScrollToEmail ? "Jump to this email in the chronology" : undefined}
                onClick={() => onScrollToEmail?.(email.id)}
                onKeyDown={(event) => {
                  if (!onScrollToEmail) return;
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onScrollToEmail(email.id);
                  }
                }}
              >
                <div className="chain-order-meta">
                  <strong>{email.from_addr || "Unknown sender"}</strong>
                  <span>{formatDateTime(email.date_utc, timeZone)}</span>
                </div>
                <h3>{email.subject}</h3>
                <p>{snippet(email.body_text)}</p>
                <div className="chain-order-badges">
                  {email.chain_date_conflict && (
                    <span className="badge warn">
                      <AlertTriangle size={13} /> order conflict
                    </span>
                  )}
                  {email.manual_chain_order !== null && email.manual_chain_order !== undefined && (
                    <span className="badge">manual #{email.manual_chain_order + 1}</span>
                  )}
                  {email.source_kind === "quoted" && <span className="badge">quoted</span>}
                </div>
              </div>
            </article>
          ))}
        </div>

        <footer>
          <button className="ghost-button" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="save-button" type="button" disabled={saving} onClick={() => void saveOrder()}>
            <Save size={16} /> {saving ? "Saving..." : "Save order"}
          </button>
        </footer>
      </aside>
    </div>
  );
}

function dropPositionForEvent(event: DragEvent<HTMLElement>): DropPosition {
  const rect = event.currentTarget.getBoundingClientRect();
  return event.clientY > rect.top + rect.height / 2 ? "after" : "before";
}

function formatDateTime(value?: string | null, timeZone?: string) {
  const date = validDate(value);
  if (!date) return value ? "Invalid date" : "No date";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone
  }).format(date);
}

function validDate(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function stripSubjectPrefix(value: string) {
  return value.replace(/^(\s*(re|fw|fwd):\s*)+/i, "").trim() || "(no subject)";
}

function snippet(value: string) {
  const text = value.replace(/\s+/g, " ").trim();
  if (!text) return "No body captured.";
  return text.length > 180 ? `${text.slice(0, 180).trimEnd()}...` : text;
}
