import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Edit3,
  ExternalLink,
  FileSearch,
  FileText,
  ListTree,
  Mail,
  MessageSquareText,
  Paperclip,
  Plus,
  Quote,
  Scissors,
  Sparkles,
  Tag as TagIcon,
  Trash2,
  X
} from "lucide-react";
import type { EmailRecord, RelationState, Tag } from "../types";
import { EmailHtmlFrame } from "./EmailHtmlFrame";

type Props = {
  email: EmailRecord;
  selected: boolean;
  onSelect: () => void;
  onOpenChain: () => void;
  onOpenDuplicates: () => void;
  onOpenSnip: () => void;
  onOpenIngestMap: () => void;
  mapReady?: boolean;
  mapTitle?: string;
  onOpenSource: () => void;
  onDelete: () => Promise<void>;
  onSaveNotes: (notes: string) => Promise<void>;
  onToggleImportant: () => Promise<void>;
  relationState?: RelationState | null;
  timeZone?: string;
  availableTags?: Tag[];
  onAddTag?: (tagId: number) => Promise<void> | void;
  onRemoveTag?: (tagId: number) => Promise<void> | void;
  onCreateTag?: (name: string) => Promise<void> | void;
  selectMode?: boolean;
  checked?: boolean;
  onToggleChecked?: () => void;
  flash?: boolean;
};

const PREVIEW_LIMIT = 2500;
const NOTES_TEXTAREA_DEFAULT_HEIGHT = 88;
const NOTES_TEXTAREA_MAX_HEIGHT = 180;

export function EmailCard({
  email,
  selected,
  onSelect,
  onOpenChain,
  onOpenDuplicates,
  onOpenSnip,
  onOpenIngestMap,
  mapReady = true,
  mapTitle = "Show where this email's parsed text went",
  onOpenSource,
  onDelete,
  onSaveNotes,
  onToggleImportant,
  relationState,
  timeZone,
  availableTags = [],
  onAddTag,
  onRemoveTag,
  onCreateTag,
  selectMode = false,
  checked = false,
  onToggleChecked,
  flash = false
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [tagMenuOpen, setTagMenuOpen] = useState(false);
  const [newTagName, setNewTagName] = useState("");
  const [renderMode, setRenderMode] = useState<"text" | "rendered">("text");
  const [draftNotes, setDraftNotes] = useState(email.notes || "");
  const [notesDirty, setNotesDirty] = useState(false);
  const [notesSaving, setNotesSaving] = useState(false);
  const [importantSaving, setImportantSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const notesRef = useRef<HTMLTextAreaElement>(null);
  const hasRenderedHtml = Boolean(email.body_html_sanitized.trim());
  const normalizedEmailBody = useMemo(() => normalizedBody(email.body_text), [email.body_text]);
  const compactPreview = normalizedEmailBody.length > PREVIEW_LIMIT;
  const overflowing = compactPreview;

  useEffect(() => {
    if (!compactPreview) setExpanded(false);
  }, [compactPreview]);

  useEffect(() => {
    // Pull in external note changes unless the user has unsaved local edits.
    if (!notesDirty) setDraftNotes(email.notes || "");
  }, [email.notes, notesDirty]);

  useLayoutEffect(() => {
    const el = notesRef.current;
    if (!el) return;
    el.style.height = `${NOTES_TEXTAREA_DEFAULT_HEIGHT}px`;
    const nextHeight = Math.min(
      Math.max(el.scrollHeight, NOTES_TEXTAREA_DEFAULT_HEIGHT),
      NOTES_TEXTAREA_MAX_HEIGHT
    );
    el.style.height = `${nextHeight}px`;
    el.style.overflowY = el.scrollHeight > NOTES_TEXTAREA_MAX_HEIGHT ? "auto" : "hidden";
  }, [draftNotes]);

  useEffect(() => {
    if (!expanded) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setExpanded(false);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [expanded]);

  function toggle(event: { stopPropagation: () => void }) {
    event.stopPropagation();
    setExpanded((value) => !value);
  }

  async function commitNotes() {
    if (!notesDirty) return;
    if ((draftNotes || "") === (email.notes || "")) {
      setNotesDirty(false);
      return;
    }
    setNotesSaving(true);
    try {
      await onSaveNotes(draftNotes);
      setNotesDirty(false);
    } finally {
      setNotesSaving(false);
    }
  }

  async function toggleImportant(event: { stopPropagation: () => void }) {
    event.stopPropagation();
    if (importantSaving) return;
    setImportantSaving(true);
    try {
      await onToggleImportant();
    } finally {
      setImportantSaving(false);
    }
  }

  async function deleteCard(event: { stopPropagation: () => void }) {
    event.stopPropagation();
    if (deleting) return;
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  }

  return (
    <article
      id={`email-${email.id}`}
      className={[
        "email-card",
        selected ? "selected" : "",
        email.important ? "important" : "",
        selectMode ? "select-mode" : "",
        selectMode && checked ? "select-checked" : "",
        relationState?.active ? "relation-active" : "",
        relationState?.focused ? "relation-focus" : "",
        relationState && !relationState.active ? "relation-muted" : "",
        relationState?.confidence === "low" ? "relation-low" : "",
        flash ? "card-flash" : ""
      ]
        .filter(Boolean)
        .join(" ")}
      role="button"
      tabIndex={0}
      onDoubleClick={(event) => {
        if (isInteractiveTarget(event.target)) return;
        onSelect();
      }}
      onKeyDown={(event) => {
        if (isInteractiveTarget(event.target)) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
    >
      {selectMode && (
        <label className="card-select" onClick={(event) => event.stopPropagation()}>
          <input
            type="checkbox"
            checked={checked}
            onChange={() => onToggleChecked?.()}
            aria-label={`Select email ${email.id} for bulk tagging`}
          />
        </label>
      )}
      <div className="email-time">
        <span>{formatDay(email.date_utc, timeZone)}</span>
        <strong>{formatTime(email.date_utc, timeZone)}</strong>
        <div className="badges">
            {email.doc_id && (
              <span className="badge doc-id" title="Document ID">
                {email.doc_id}
              </span>
            )}
            {email.source_import_mode === "manual" ? (
              <span className="badge">
                <Edit3 size={13} /> manual
              </span>
            ) : email.parse_confidence === "high" ? (
              <span className="badge ok">
                <CheckCircle2 size={13} /> parsed
              </span>
            ) : (
              <span className="badge warn">
                <AlertTriangle size={13} /> {email.parse_confidence}
              </span>
            )}
            {email.user_edited && email.source_import_mode !== "manual" && (
              <span className="badge">
                <Edit3 size={13} /> edited
              </span>
            )}
            {email.source_kind === "quoted" && (
              <span className="badge">
                <Quote size={13} /> quoted
              </span>
            )}
            {email.source_kind === "attached" && (
              <span
                className="badge"
                title={
                  attachedParentId(email)
                    ? `Email parsed from an attachment on #${attachedParentId(email)}`
                    : "Email parsed from an attachment"
                }
              >
                <Mail size={13} /> attachment
                {attachedParentId(email) ? <> of #{attachedParentId(email)}</> : null}
              </span>
            )}
            {boundaryBadgeLabel(email) && (
              <span className="badge" title={email.boundary_evidence.join(" | ") || "Boundary evidence"}>
                {boundaryBadgeLabel(email)}
              </span>
            )}
            {email.chain_date_conflict && (
              <span className="badge warn" title="Parsed date conflicts with source-chain position">
                <AlertTriangle size={13} /> order conflict
              </span>
            )}
            {email.flags.includes("boilerplate_stripped") && (
              <span className="badge" title="Disclaimer boilerplate removed">
                <Sparkles size={13} /> cleaned
              </span>
            )}
            {email.attachments.length > 0 && (
              <span className="badge">
                <Paperclip size={13} /> {email.attachments.length}
              </span>
            )}
          </div>
      </div>
      <div className="email-body">
        <div className="email-main">
          <div className="email-actions-row" aria-label="Email actions">
            {email.suspected_duplicate_count > 0 && (
              <button
                className="chain-button duplicate-button"
                type="button"
                title="Review suspected duplicates"
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenDuplicates();
                }}
                onKeyDown={(event) => event.stopPropagation()}
              >
                <Copy size={14} /> Duplicates {email.suspected_duplicate_count}
              </button>
            )}
            <button
              className={`chain-button ${relationState?.focused ? "active" : ""}`}
              type="button"
              title="Show the chain sidebar and highlight related emails"
              onClick={(event) => {
                event.stopPropagation();
                onOpenChain();
              }}
              onKeyDown={(event) => event.stopPropagation()}
            >
              <ListTree size={14} /> Chain
            </button>
            <button
              className="chain-button snip-button"
              type="button"
              title="Open Snip view"
              onClick={(event) => {
                event.stopPropagation();
                onOpenSnip();
              }}
              onKeyDown={(event) => event.stopPropagation()}
            >
              <Scissors size={14} /> Snip
            </button>
            <button
              className="chain-button ingest-map-button"
              type="button"
              title={mapTitle}
              disabled={!mapReady}
              onClick={(event) => {
                event.stopPropagation();
                if (!mapReady) return;
                onOpenIngestMap();
              }}
              onKeyDown={(event) => event.stopPropagation()}
            >
              <FileSearch size={14} /> Map
            </button>
            <button
              className={`important-button ${email.important ? "active" : ""}`}
              type="button"
              title={email.important ? "Unmark important" : "Mark important"}
              aria-pressed={email.important}
              disabled={importantSaving}
              onClick={(event) => void toggleImportant(event)}
              onKeyDown={(event) => event.stopPropagation()}
            >
              !
            </button>
            <button
              className="chain-button delete-card-button"
              type="button"
              title="Move email to trash"
              disabled={deleting}
              onClick={(event) => void deleteCard(event)}
              onKeyDown={(event) => event.stopPropagation()}
            >
              <Trash2 size={14} /> {deleting ? "Trash..." : "Trash"}
            </button>
          </div>
          <div className="email-card-top">
            <div className="email-participants">
              <span>
                <em>From</em> {email.from_addr || "Unknown sender"}
              </span>
              <span>
                <em>To</em> {formatRecipients(email.to)}
              </span>
              {email.cc.length > 0 && (
                <span>
                  <em>Cc</em> {formatRecipients(email.cc)}
                </span>
              )}
            </div>
          </div>
          <h2>{email.subject}</h2>
          <div className="email-tags" onClick={(event) => event.stopPropagation()}>
            {email.tags.map((tag) => (
              <span className="tag-chip" key={tag.id} style={tagChipStyle(tag.color)}>
                {tag.name}
                {onRemoveTag && (
                  <button
                    type="button"
                    className="tag-chip-remove"
                    title={`Remove ${tag.name}`}
                    onClick={() => void onRemoveTag(tag.id)}
                  >
                    <X size={11} />
                  </button>
                )}
              </span>
            ))}
            {onAddTag && (
              <div className="tag-add">
                <button
                  type="button"
                  className="tag-add-button"
                  title="Add a tag"
                  onClick={() => setTagMenuOpen((value) => !value)}
                >
                  <TagIcon size={12} /> <Plus size={11} />
                </button>
                {tagMenuOpen && (
                  <div className="tag-menu">
                    {unappliedTags(availableTags, email.tags).map((tag) => (
                      <button
                        type="button"
                        key={tag.id}
                        className="tag-menu-item"
                        onClick={async () => {
                          await onAddTag(tag.id);
                          setTagMenuOpen(false);
                        }}
                      >
                        <span className="tag-dot" style={{ background: tag.color }} />
                        {tag.name}
                      </button>
                    ))}
                    {onCreateTag && (
                      <div className="tag-menu-create">
                        <input
                          type="text"
                          value={newTagName}
                          placeholder="New tag…"
                          onChange={(event) => setNewTagName(event.target.value)}
                          onKeyDown={async (event) => {
                            event.stopPropagation();
                            if (event.key === "Enter" && newTagName.trim()) {
                              await onCreateTag(newTagName.trim());
                              setNewTagName("");
                              setTagMenuOpen(false);
                            }
                          }}
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
          {relationState?.active && (
            <div className="relation-strip">
              <strong>{relationState.label}</strong>
              <span>{relationState.summary}</span>
            </div>
          )}
          <div className="source-row" title={sourceTitle(email)}>
            <FileText size={14} />
            <span>Source</span>
            {email.source_openable ? (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenSource();
                }}
              >
                <ExternalLink size={13} />
                {email.source_file_display}
              </button>
            ) : (
              <strong>{email.source_file_display}</strong>
            )}
          </div>
          {expanded && hasRenderedHtml && (
            <div className="render-mode-toggle" role="group" aria-label="Email body view">
              <button
                className={renderMode === "text" ? "active" : ""}
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  setRenderMode("text");
                }}
              >
                Text
              </button>
              <button
                className={renderMode === "rendered" ? "active" : ""}
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  setRenderMode("rendered");
                }}
              >
                Rendered
              </button>
            </div>
          )}
          {expanded && hasRenderedHtml && renderMode === "rendered" ? (
            <EmailHtmlFrame emailId={email.id} html={email.body_html_sanitized} />
          ) : (
            <p className={!expanded && compactPreview ? "clamped" : ""}>
              {bodyText(normalizedEmailBody, !expanded && compactPreview)}
            </p>
          )}
          {(overflowing || expanded) && (
            <span
              className="more-toggle"
              role="button"
              tabIndex={0}
              onClick={toggle}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  toggle(event);
                }
              }}
            >
              {expanded ? "Show less" : "Show more"}
            </span>
          )}
        </div>
        <aside className="email-notes" onClick={(event) => event.stopPropagation()}>
          <header>
            <MessageSquareText size={14} />
            <span>Notes</span>
            <small>
              {notesSaving ? "Saving…" : notesDirty ? "Unsaved" : email.notes ? "Saved" : ""}
            </small>
          </header>
          <textarea
            ref={notesRef}
            value={draftNotes}
            placeholder="Add notes for this email…"
            onChange={(event) => {
              setDraftNotes(event.target.value);
              setNotesDirty(true);
            }}
            onBlur={() => void commitNotes()}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              event.stopPropagation();
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                event.preventDefault();
                event.currentTarget.blur();
              }
            }}
          />
        </aside>
      </div>
    </article>
  );
}

function formatDay(value?: string | null, timeZone?: string) {
  const date = validDate(value);
  if (!date) return value ? "Invalid date" : "No date";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone }).format(date);
}

function formatTime(value?: string | null, timeZone?: string) {
  const date = validDate(value);
  if (!date) return "--:--";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone }).format(date);
}

function validDate(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function normalizedBody(value: string) {
  return value
    .replace(/\r\n/g, "\n")
    .replace(/[^\S\n]+/g, " ")
    .replace(/ *\n+ */g, "\n")
    .trim();
}

function bodyText(value: string, truncate: boolean) {
  const text = normalizedBody(value);
  if (!text) return "No plain-text body captured.";
  if (truncate && text.length > PREVIEW_LIMIT) return `${text.slice(0, PREVIEW_LIMIT).trimEnd()}...`;
  return text;
}

function snippet(value: string) {
  // Compress whitespace for a denser preview: collapse runs of spaces/tabs to one
  // space and any run of blank lines to a single line break.
  const text = value
    .replace(/\r\n/g, "\n")
    .replace(/[^\S\n]+/g, " ")
    .replace(/ *\n+ */g, "\n")
    .trim();
  if (!text) return "No plain-text body captured.";
  if (text.length > PREVIEW_LIMIT) return `${text.slice(0, PREVIEW_LIMIT).trimEnd()}…`;
  return text;
}

function formatRecipients(values: string[]) {
  if (!values.length) return "No recipients";
  return values.join(", ");
}

function unappliedTags(available: Tag[], applied: Tag[]): Tag[] {
  const appliedIds = new Set(applied.map((tag) => tag.id));
  return available.filter((tag) => !appliedIds.has(tag.id));
}

function tagChipStyle(color: string) {
  // Tint the chip from its color: soft fill + matching border/text so the label
  // stays readable on the light card.
  return {
    background: `${color}1f`,
    borderColor: `${color}66`,
    color
  } as const;
}

function attachedParentId(email: EmailRecord) {
  return email.parent_email_id ?? email.chain_source_id ?? null;
}

function boundaryBadgeLabel(email: EmailRecord) {
  const method = email.boundary_method;
  if (!method) return "";

  // These methods are already represented by clearer user-facing badges:
  // parsed/manual/quoted/attachment. Keep boundary badges only for non-default
  // or diagnostic boundary methods that add new information.
  if (method === "mime" && email.source_kind === "standalone") return "";
  if (method === "manual" && email.source_import_mode === "manual") return "";
  if (method === "quoted_text" && email.source_kind === "quoted") return "";
  if (method === "attached_email" && email.source_kind === "attached") return "";
  if (method.includes("outlook")) return "";

  return method.replace(/_/g, " ");
}

function sourceTitle(email: EmailRecord) {
  const parts = [email.source_import_mode.replace(/_/g, " ")];
  if (email.source_size) parts.push(`${email.source_size.toLocaleString()} bytes`);
  if (email.source_mtime) parts.push(`modified ${email.source_mtime}`);
  if (email.source_sha256) parts.push(`sha256 ${email.source_sha256}`);
  return parts.join(" | ");
}

function isInteractiveTarget(target: EventTarget) {
  return target instanceof HTMLElement
    ? Boolean(target.closest("button, input, textarea, select, a, [role='dialog']"))
    : false;
}
