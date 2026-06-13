import { Check, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Tag } from "../types";

type Props = {
  text: string;
  selectedTagId: number | null;
  tags: Tag[];
  disabled?: boolean;
  onTextChange: (value: string) => void;
  onTagChange: (tagId: number | null) => void;
  onApply: () => void;
  onClear: () => void;
};

export function UnifiedFilterBox({
  text,
  selectedTagId,
  tags,
  disabled = false,
  onTextChange,
  onTagChange,
  onApply,
  onClear
}: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const selectedTag = tags.find((tag) => tag.id === selectedTagId) ?? null;
  const tagQuery = text.trim().toLowerCase();
  const sortedTags = useMemo(() => {
    const matching = tagQuery
      ? tags.filter((tag) => tag.name.toLowerCase().includes(tagQuery))
      : tags;
    const visible = matching.length ? matching : tags;
    return [...visible].sort((a, b) => {
      if (a.id === selectedTagId) return -1;
      if (b.id === selectedTagId) return 1;
      return a.name.localeCompare(b.name);
    });
  }, [selectedTagId, tagQuery, tags]);
  const hasFilters = Boolean(text.trim()) || selectedTagId !== null;

  useEffect(() => {
    function onDocumentPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocumentPointerDown);
    return () => document.removeEventListener("mousedown", onDocumentPointerDown);
  }, []);

  function toggleTag(tagId: number) {
    onTagChange(selectedTagId === tagId ? null : tagId);
    setOpen(true);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }

  return (
    <div className={`unified-filter ${open ? "open" : ""}`} ref={rootRef}>
      <div className="unified-filter-shell">
        <Search size={16} />
        <div className="unified-filter-tokens" onClick={() => inputRef.current?.focus()}>
          {selectedTag && (
            <span className="unified-filter-chip" style={tagChipStyle(selectedTag.color)}>
              <span>{selectedTag.name}</span>
              <button
                type="button"
                title={`Remove ${selectedTag.name}`}
                aria-label={`Remove ${selectedTag.name}`}
                disabled={disabled}
                onClick={(event) => {
                  event.stopPropagation();
                  onTagChange(null);
                  inputRef.current?.focus();
                }}
              >
                <X size={12} />
              </button>
            </span>
          )}
          <input
            ref={inputRef}
            value={text}
            disabled={disabled}
            placeholder={selectedTag ? "Search within tag..." : tags.length ? "Search text or add tags..." : "Search emails..."}
            onFocus={() => setOpen(true)}
            onChange={(event) => onTextChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                setOpen(false);
                onApply();
              }
              if (event.key === "Escape") {
                setOpen(false);
              }
            }}
          />
        </div>
        {hasFilters && (
          <button
            className="unified-filter-clear"
            type="button"
            title="Clear filters"
            aria-label="Clear filters"
            disabled={disabled}
            onClick={() => {
              setOpen(false);
              onClear();
            }}
          >
            <X size={14} />
          </button>
        )}
      </div>

      {open && !disabled && (
        <div className="unified-filter-menu" role="listbox" aria-label="Filter suggestions">
          <div className="unified-filter-menu-section">
            <div className="unified-filter-menu-label">Text search</div>
            <button
              type="button"
              className="unified-filter-option search"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                setOpen(false);
                onApply();
              }}
            >
              <Search size={15} />
              <span>{text.trim() ? `Search for "${text.trim()}"` : "Search all email text"}</span>
            </button>
          </div>
          <div className="unified-filter-menu-section">
            <div className="unified-filter-menu-label">Tags</div>
            {tags.length === 0 ? (
              <div className="unified-filter-empty">No tags yet</div>
            ) : (
              sortedTags.map((tag) => {
                const active = tag.id === selectedTagId;
                return (
                  <button
                    type="button"
                    className={`unified-filter-option ${active ? "active" : ""}`}
                    key={tag.id}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => toggleTag(tag.id)}
                  >
                    <span className="tag-dot" style={{ background: tag.color }} />
                    <span>{tag.name}</span>
                    {active && <Check size={15} />}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function tagChipStyle(color: string) {
  return {
    background: `${color}1f`,
    borderColor: `${color}66`,
    color
  } as const;
}
