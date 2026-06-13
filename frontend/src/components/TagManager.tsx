import { useState } from "react";
import { Check, Plus, Trash2, X } from "lucide-react";
import type { Tag } from "../types";

type Props = {
  tags: Tag[];
  onCreate: (name: string, color: string) => Promise<void>;
  onUpdate: (tagId: number, payload: { name?: string; color?: string }) => Promise<void>;
  onDelete: (tagId: number) => Promise<void>;
};

const PALETTE = [
  "#ef4444",
  "#f97316",
  "#eab308",
  "#22c55e",
  "#06b6d4",
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#64748b"
];

export function TagManager({ tags, onCreate, onUpdate, onDelete }: Props) {
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(PALETTE[5]);
  const [busy, setBusy] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  async function create() {
    const name = newName.trim();
    if (!name || busy) return;
    setBusy(true);
    try {
      await onCreate(name, newColor);
      setNewName("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tag-manager">
      <div className="tag-manager-create">
        <input
          type="color"
          value={newColor}
          onChange={(event) => setNewColor(event.target.value)}
          title="Tag color"
          aria-label="New tag color"
        />
        <input
          type="text"
          value={newName}
          placeholder="New tag name"
          onChange={(event) => setNewName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void create();
          }}
          disabled={busy}
        />
        <button type="button" onClick={() => void create()} disabled={busy || !newName.trim()}>
          <Plus size={14} /> Add
        </button>
      </div>
      {tags.length === 0 ? (
        <p className="tag-manager-empty">No tags yet. Create one to start labeling emails.</p>
      ) : (
        <ul className="tag-manager-list">
          {tags.map((tag) => (
            <li key={tag.id}>
              <input
                type="color"
                value={tag.color}
                onChange={(event) => void onUpdate(tag.id, { color: event.target.value })}
                title="Change color"
                aria-label={`Color for ${tag.name}`}
              />
              <input
                type="text"
                defaultValue={tag.name}
                onBlur={(event) => {
                  const value = event.target.value.trim();
                  if (value && value !== tag.name) void onUpdate(tag.id, { name: value });
                }}
                aria-label={`Rename ${tag.name}`}
              />
              {confirmDeleteId === tag.id ? (
                <span className="tag-manager-confirm">
                  <button
                    type="button"
                    className="danger"
                    title="Confirm delete"
                    onClick={async () => {
                      await onDelete(tag.id);
                      setConfirmDeleteId(null);
                    }}
                  >
                    <Check size={14} />
                  </button>
                  <button type="button" title="Cancel" onClick={() => setConfirmDeleteId(null)}>
                    <X size={14} />
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  title="Delete tag"
                  onClick={() => setConfirmDeleteId(tag.id)}
                >
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
