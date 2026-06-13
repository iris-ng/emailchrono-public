import { ChangeEvent, DragEvent, useRef, useState } from "react";
import { FolderOpen, UploadCloud } from "lucide-react";
import type { IngestJob, Tag } from "../types";

type Props = {
  onUpload: (files: File[], tagIds: number[], containsCjk: boolean) => Promise<void>;
  onFolderImport: (
    folderPath: string,
    recursive: boolean,
    tagIds: number[],
    containsCjk: boolean
  ) => Promise<void>;
  availableTags?: Tag[];
  activeJob?: IngestJob | null;
  defaultContainsCjk?: boolean;
};

type UploadMode = "files" | "folder";

export function UploadDropzone({
  onUpload,
  onFolderImport,
  availableTags = [],
  activeJob,
  defaultContainsCjk = false
}: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [mode, setMode] = useState<UploadMode>("files");
  const [dragging, setDragging] = useState(false);
  const [localBusy, setLocalBusy] = useState(false);
  const [folderPath, setFolderPath] = useState("");
  const [recursive, setRecursive] = useState(true);
  const [containsCjk, setContainsCjk] = useState(defaultContainsCjk);
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  const busy = localBusy || activeJob?.status === "running";

  function toggleTag(tagId: number) {
    setSelectedTagIds((current) =>
      current.includes(tagId) ? current.filter((id) => id !== tagId) : [...current, tagId]
    );
  }

  async function upload(files: FileList | File[]) {
    const emailFiles = Array.from(files).filter((file) => {
      const name = file.name.toLowerCase();
      return (
        name.endsWith(".eml") ||
        name.endsWith(".msg") ||
        name.endsWith(".pdf") ||
        name.endsWith(".docx")
      );
    });
    if (!emailFiles.length) return;
    setLocalBusy(true);
    try {
      await onUpload(emailFiles, selectedTagIds, containsCjk);
    } finally {
      setLocalBusy(false);
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void upload(event.dataTransfer.files);
  }

  function onChange(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) void upload(event.target.files);
    event.target.value = "";
  }

  async function importFolder() {
    const trimmed = folderPath.trim();
    if (!trimmed || busy) return;
    setLocalBusy(true);
    try {
      await onFolderImport(trimmed, recursive, selectedTagIds, containsCjk);
    } finally {
      setLocalBusy(false);
    }
  }

  return (
    <div
      className={`upload-zone ${dragging ? "dragging" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      {mode === "folder" ? <FolderOpen size={28} /> : <UploadCloud size={28} />}
      <div className="upload-mode-toggle" role="tablist" aria-label="Upload mode">
        <button
          className={mode === "files" ? "active" : ""}
          type="button"
          onClick={() => setMode("files")}
          disabled={busy}
        >
          Files
        </button>
        <button
          className={mode === "folder" ? "active" : ""}
          type="button"
          onClick={() => setMode("folder")}
          disabled={busy}
        >
          Folder path
        </button>
      </div>
      <h2>{uploadTitle(activeJob, mode, localBusy)}</h2>
      {mode === "folder" ? (
        <div className="folder-import">
          <input
            type="text"
            value={folderPath}
            onChange={(event) => setFolderPath(event.target.value)}
            placeholder="C:\\Path\\To\\Email Folder"
            disabled={busy}
          />
          <label className="recursive-toggle">
            <input
              type="checkbox"
              checked={recursive}
              onChange={(event) => setRecursive(event.target.checked)}
              disabled={busy}
            />
            <span>Read subfolders</span>
          </label>
          <button type="button" onClick={() => void importFolder()} disabled={busy || !folderPath.trim()}>
            Import folder
          </button>
        </div>
      ) : (
        <>
          <p>Drop files here or choose them from disk.</p>
          <button type="button" onClick={() => inputRef.current?.click()} disabled={busy}>
            Choose files
          </button>
        </>
      )}
      <label className="cjk-toggle" onClick={(event) => event.stopPropagation()}>
        <input
          type="checkbox"
          checked={containsCjk}
          onChange={(event) => setContainsCjk(event.target.checked)}
          disabled={busy}
        />
        <span>Contains Chinese-language content</span>
      </label>
      {availableTags.length > 0 && (
        <div className="upload-tags" onClick={(event) => event.stopPropagation()}>
          <span className="upload-tags-label">Tag uploads</span>
          <div className="upload-tags-options">
            {availableTags.map((tag) => {
              const active = selectedTagIds.includes(tag.id);
              return (
                <button
                  type="button"
                  key={tag.id}
                  className={`upload-tag-chip ${active ? "active" : ""}`}
                  style={
                    active
                      ? { background: `${tag.color}1f`, borderColor: tag.color, color: tag.color }
                      : undefined
                  }
                  onClick={() => toggleTag(tag.id)}
                  disabled={busy}
                >
                  <span className="tag-dot" style={{ background: tag.color }} />
                  {tag.name}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <input ref={inputRef} type="file" accept=".eml,.msg,.pdf,.docx" multiple onChange={onChange} />
    </div>
  );
}

function uploadTitle(job: IngestJob | null | undefined, mode: UploadMode, localBusy: boolean) {
  if (job?.status === "running") {
    return `Parsing ${job.processed_files} of ${job.total_files}`;
  }
  if (localBusy) return "Starting parser...";
  return mode === "folder" ? "Import a local folder" : "Upload email files";
}
