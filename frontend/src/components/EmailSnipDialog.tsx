import { useEffect, useMemo, useRef, useState } from "react";
import type { MutableRefObject, PointerEvent, RefObject } from "react";
import { Check, CheckCheck, Pencil, RotateCcw, Scissors, Trash2, X } from "lucide-react";
import type { EmailRecord, EmailSnipPartDraft } from "../types";

type Props = {
  email: EmailRecord | null;
  saving: boolean;
  onClose: () => void;
  onPreview: (emailId: number, splitOffsets: number[]) => Promise<EmailSnipPartDraft[]>;
  onApply: (splitOffsets: number[], parts: EmailSnipPartDraft[]) => Promise<void>;
};

type BoundaryCandidate = {
  offset: number;
  lineIndex: number;
  y: number;
};

type Stage = "mark" | "review";

export function EmailSnipDialog({ email, saving, onClose, onPreview, onApply }: Props) {
  const [offsets, setOffsets] = useState<number[]>([]);
  const [drafts, setDrafts] = useState<EmailSnipPartDraft[]>([]);
  const [stage, setStage] = useState<Stage>("mark");
  const [drawingY, setDrawingY] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Array<HTMLDivElement | null>>([]);
  const drawing = useRef(false);

  const body = useMemo(() => normalizeBody(email?.body_text ?? ""), [email]);
  const lines = useMemo(() => body.split("\n"), [body]);
  const lineStarts = useMemo(() => lineStartOffsets(lines), [lines]);
  const parts = useMemo(() => splitBody(body, offsets), [body, offsets]);
  const approvedCount = drafts.filter((draft) => draft.approved).length;
  const allApproved = drafts.length > 0 && approvedCount === drafts.length;

  useEffect(() => {
    setOffsets([]);
    setDrafts([]);
    setStage("mark");
    setDrawingY(null);
    setError("");
  }, [email?.id]);

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
  const activeEmail = email;

  function pointerY(event: PointerEvent<HTMLDivElement>) {
    const scroll = scrollRef.current;
    if (!scroll) return 0;
    const rect = scroll.getBoundingClientRect();
    return event.clientY - rect.top + scroll.scrollTop;
  }

  function startDraw(event: PointerEvent<HTMLDivElement>) {
    if (event.target instanceof HTMLElement && event.target.closest("button")) return;
    drawing.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrawingY(pointerY(event));
    setError("");
  }

  function moveDraw(event: PointerEvent<HTMLDivElement>) {
    if (!drawing.current) return;
    setDrawingY(pointerY(event));
  }

  function finishDraw(event: PointerEvent<HTMLDivElement>) {
    if (!drawing.current) return;
    drawing.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const candidate = nearestBoundary(pointerY(event));
    setDrawingY(null);
    if (!candidate) {
      setError("No valid split line is available for this email body.");
      return;
    }
    setOffsets((current) => {
      if (current.includes(candidate.offset)) return current;
      setDrafts([]);
      setStage("mark");
      return [...current, candidate.offset].sort((a, b) => a - b);
    });
  }

  function nearestBoundary(y: number) {
    const candidates = boundaryCandidates();
    if (!candidates.length) return null;
    return candidates.reduce((best, candidate) =>
      Math.abs(candidate.y - y) < Math.abs(best.y - y) ? candidate : best
    );
  }

  function boundaryCandidates(): BoundaryCandidate[] {
    const scroll = scrollRef.current;
    if (!scroll || lines.length < 2) return [];
    const scrollRect = scroll.getBoundingClientRect();
    const candidates: BoundaryCandidate[] = [];
    for (let index = 0; index < lines.length - 1; index += 1) {
      const current = lineRefs.current[index];
      const next = lineRefs.current[index + 1];
      if (!current || !next) continue;
      const y =
        (current.getBoundingClientRect().bottom + next.getBoundingClientRect().top) / 2 -
        scrollRect.top +
        scroll.scrollTop;
      candidates.push({ offset: lineStarts[index + 1], lineIndex: index, y });
    }
    return candidates;
  }

  async function openReview() {
    if (!offsets.length) {
      setError("Add at least one separator before reviewing Snip cards.");
      return;
    }
    setError("");
    setPreviewing(true);
    try {
      const preview = await onPreview(activeEmail.id, offsets);
      setDrafts(preview);
      setStage("review");
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setPreviewing(false);
    }
  }

  async function applySnip() {
    if (!drafts.length) {
      setError("Review the proposed Snip cards before ingesting.");
      return;
    }
    if (!allApproved) {
      setError("Approve every proposed Snip card before ingesting.");
      return;
    }
    setError("");
    await onApply(offsets, drafts);
  }

  function removeOffset(offsetToRemove: number) {
    drawing.current = false;
    setDrawingY(null);
    setError("");
    setDrafts([]);
    setStage("mark");
    setOffsets((current) => current.filter((offset) => offset !== offsetToRemove));
  }

  function updateDraft(partIndex: number, patch: Partial<EmailSnipPartDraft>) {
    setDrafts((current) =>
      current.map((draft) =>
        draft.part_index === partIndex ? { ...draft, ...patch, approved: false } : draft
      )
    );
  }

  function approveDraft(partIndex: number) {
    setDrafts((current) =>
      current.map((draft) => (draft.part_index === partIndex ? { ...draft, approved: true } : draft))
    );
  }

  function approveAll() {
    setDrafts((current) => current.map((draft) => ({ ...draft, approved: true })));
    setError("");
  }

  return (
    <div className="snip-scrim" role="dialog" aria-modal="true" onClick={onClose}>
      <section className="snip-dialog" onClick={(event) => event.stopPropagation()}>
        <header className="snip-header">
          <div>
            <p className="eyebrow">{stage === "review" ? "Snip confirmation" : "Snip view"}</p>
            <h2>{activeEmail.subject || "(no subject)"}</h2>
            <span>
              {activeEmail.from_addr || "Unknown sender"} - {parts.length} cards after split
            </span>
          </div>
          <div className="snip-actions">
            {stage === "review" ? (
              <>
                <button className="ghost-button" type="button" disabled={saving} onClick={() => setStage("mark")}>
                  <Pencil size={15} /> Adjust lines
                </button>
                <button className="ghost-button" type="button" disabled={saving || allApproved} onClick={approveAll}>
                  <CheckCheck size={15} /> Approve all
                </button>
                <button className="save-button" type="button" disabled={saving || !allApproved} onClick={() => void applySnip()}>
                  <Scissors size={16} /> {saving ? "Ingesting" : "Ingest approved"}
                </button>
              </>
            ) : (
              <>
                <button
                  className="ghost-button"
                  type="button"
                  disabled={!offsets.length || saving || previewing}
                  onClick={() => {
                    setOffsets([]);
                    setDrafts([]);
                    setError("");
                  }}
                >
                  <RotateCcw size={15} /> Reset
                </button>
                <button
                  className="save-button"
                  type="button"
                  disabled={saving || previewing || !offsets.length}
                  onClick={() => void openReview()}
                >
                  <Scissors size={16} /> {previewing ? "Preparing" : "Review Snip"}
                </button>
              </>
            )}
            <button className="icon-button" type="button" disabled={saving} onClick={onClose} title="Close">
              <X size={18} />
            </button>
          </div>
        </header>

        {error && <div className="snip-error">{error}</div>}

        {stage === "review" ? (
          <SnipReview
            drafts={drafts}
            approvedCount={approvedCount}
            onApprove={approveDraft}
            onUpdate={updateDraft}
          />
        ) : (
          <SnipMarker
            drawingY={drawingY}
            lineRefs={lineRefs}
            lines={lines}
            lineStarts={lineStarts}
            offsets={offsets}
            parts={parts}
            scrollRef={scrollRef}
            onPointerCancel={() => {
              drawing.current = false;
              setDrawingY(null);
            }}
            onPointerDown={startDraw}
            onPointerMove={moveDraw}
            onPointerUp={finishDraw}
            onRemoveOffset={removeOffset}
          />
        )}
      </section>
    </div>
  );
}

function SnipMarker({
  drawingY,
  lineRefs,
  lines,
  lineStarts,
  offsets,
  parts,
  scrollRef,
  onPointerCancel,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onRemoveOffset
}: {
  drawingY: number | null;
  lineRefs: MutableRefObject<Array<HTMLDivElement | null>>;
  lines: string[];
  lineStarts: number[];
  offsets: number[];
  parts: string[];
  scrollRef: RefObject<HTMLDivElement | null>;
  onPointerCancel: () => void;
  onPointerDown: (event: PointerEvent<HTMLDivElement>) => void;
  onPointerMove: (event: PointerEvent<HTMLDivElement>) => void;
  onPointerUp: (event: PointerEvent<HTMLDivElement>) => void;
  onRemoveOffset: (offset: number) => void;
}) {
  return (
    <div className="snip-workspace">
      <div className="snip-body-pane">
        <div
          className="snip-text-scroll"
          ref={scrollRef}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerCancel}
        >
          <div className="snip-text-content">
            {drawingY !== null && <div className="snip-drawing-line" style={{ top: drawingY }} />}
            {lines.map((line, index) => (
              <div key={`${index}-${lineStarts[index]}`}>
                <div
                  className="snip-body-line"
                  ref={(node) => {
                    lineRefs.current[index] = node;
                  }}
                >
                  <span>{index + 1}</span>
                  <code>{line || " "}</code>
                </div>
                {index < lines.length - 1 && offsets.includes(lineStarts[index + 1]) && (
                  <SnipSeparator offset={lineStarts[index + 1]} onRemove={onRemoveOffset} />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      <aside className="snip-preview-pane">
        <header>
          <strong>Preview</strong>
          <span>{offsets.length} separators</span>
        </header>
        <div className="snip-preview-list">
          {parts.map((part, index) => (
            <article className="snip-preview-card" key={`${index}-${part.length}`}>
              <div>
                <strong>Card {index + 1}</strong>
                <span>{part.trim().length.toLocaleString()} chars</span>
              </div>
              <p>{part.trim() || "Empty card"}</p>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}

function SnipReview({
  drafts,
  approvedCount,
  onApprove,
  onUpdate
}: {
  drafts: EmailSnipPartDraft[];
  approvedCount: number;
  onApprove: (partIndex: number) => void;
  onUpdate: (partIndex: number, patch: Partial<EmailSnipPartDraft>) => void;
}) {
  return (
    <div className="snip-review">
      <div className="snip-review-summary">
        <strong>{approvedCount} approved</strong>
        <span>{drafts.length} proposed chronology cards</span>
      </div>
      <div className="snip-review-list">
        {drafts.map((draft) => (
          <article className={`snip-review-row ${draft.approved ? "approved" : ""}`} key={draft.part_index}>
            <section className="snip-source-segment">
              <header>
                <strong>Segment {draft.part_index}</strong>
                <span>{(draft.source_segment || "").trim().length.toLocaleString()} chars</span>
              </header>
              <pre>{draft.source_segment || ""}</pre>
            </section>
            <section className="snip-card-editor">
              <header>
                <strong>Proposed card {draft.part_index}</strong>
                <span>{draft.approved ? "Approved" : "Needs approval"}</span>
              </header>
              <div className="snip-editor-grid">
                <label>
                  <span>From</span>
                  <input
                    value={draft.from_addr}
                    onChange={(event) => onUpdate(draft.part_index, { from_addr: event.target.value })}
                  />
                </label>
                <label>
                  <span>To</span>
                  <input
                    value={draft.to.join(", ")}
                    onChange={(event) => onUpdate(draft.part_index, { to: splitList(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Cc</span>
                  <input
                    value={draft.cc.join(", ")}
                    onChange={(event) => onUpdate(draft.part_index, { cc: splitList(event.target.value) })}
                  />
                </label>
                <label>
                  <span>Date</span>
                  <input
                    value={draft.date_raw ?? ""}
                    onChange={(event) => onUpdate(draft.part_index, { date_raw: event.target.value || null })}
                    placeholder="19/03/21 14:47"
                  />
                </label>
                <label className="wide">
                  <span>Subject</span>
                  <input
                    value={draft.subject}
                    onChange={(event) => onUpdate(draft.part_index, { subject: event.target.value })}
                  />
                </label>
                <label className="wide">
                  <span>Body</span>
                  <textarea
                    value={draft.body_text}
                    onChange={(event) => onUpdate(draft.part_index, { body_text: event.target.value })}
                  />
                </label>
                <label className="wide">
                  <span>Notes</span>
                  <textarea
                    className="compact"
                    value={draft.notes}
                    onChange={(event) => onUpdate(draft.part_index, { notes: event.target.value })}
                  />
                </label>
              </div>
              <footer>
                <label className="snip-important-toggle">
                  <input
                    type="checkbox"
                    checked={draft.important}
                    onChange={(event) => onUpdate(draft.part_index, { important: event.target.checked })}
                  />
                  <span>Important</span>
                </label>
                <button className="ghost-button" type="button" onClick={() => onApprove(draft.part_index)}>
                  <Check size={15} /> {draft.approved ? "Approved" : "Approve card"}
                </button>
              </footer>
            </section>
          </article>
        ))}
      </div>
    </div>
  );
}

function SnipSeparator({
  offset,
  onRemove
}: {
  offset: number;
  onRemove: (offset: number) => void;
}) {
  return (
    <div className="snip-separator">
      <span />
      <button
        type="button"
        title="Remove separator"
        onPointerDown={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onPointerUp={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onRemove(offset);
        }}
      >
        <Trash2 size={13} />
      </button>
    </div>
  );
}

function normalizeBody(value: string) {
  return value.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function lineStartOffsets(lines: string[]) {
  const starts: number[] = [];
  let offset = 0;
  lines.forEach((line) => {
    starts.push(offset);
    offset += line.length + 1;
  });
  return starts;
}

function splitBody(body: string, offsets: number[]) {
  const boundaries = [0, ...offsets, body.length];
  return boundaries.slice(0, -1).map((start, index) => body.slice(start, boundaries[index + 1]));
}

function splitList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function readErrorMessage(err: unknown) {
  if (!(err instanceof Error)) return "Snip preview could not be prepared";
  try {
    const parsed = JSON.parse(err.message) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // Keep original message below.
  }
  return err.message || "Snip preview could not be prepared";
}
