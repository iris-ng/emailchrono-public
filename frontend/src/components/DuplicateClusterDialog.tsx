import { useEffect, useState } from "react";
import { CheckCircle2, Layers, X, Zap } from "lucide-react";
import type { DuplicateCluster, EmailRecord } from "../types";

export function DuplicateClusterDialog({
  open,
  clusters,
  loading,
  exactCount,
  busy,
  onClose,
  onResolveCluster,
  onResolveExact,
  timeZone
}: {
  open: boolean;
  clusters: DuplicateCluster[];
  loading: boolean;
  exactCount: number;
  busy: boolean;
  onClose: () => void;
  onResolveCluster: (cluster: DuplicateCluster, canonicalId: number) => void;
  onResolveExact: () => void;
  timeZone?: string;
}) {
  const [canonicalByCluster, setCanonicalByCluster] = useState<Record<string, number>>({});

  useEffect(() => {
    setCanonicalByCluster((current) => {
      const next = { ...current };
      clusters.forEach((cluster) => {
        if (next[cluster.id] === undefined) {
          next[cluster.id] = cluster.suggested_canonical_id ?? cluster.email_ids[0];
        }
      });
      return next;
    });
  }, [clusters]);

  if (!open) return null;

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
        aria-label="Review duplicate clusters"
      >
        <header>
          <div>
            <p className="eyebrow">Duplicate Review</p>
            <h2>Suspected duplicates</h2>
            <span>
              {loading
                ? "Grouping candidates..."
                : `${clusters.length} ${clusters.length === 1 ? "cluster" : "clusters"} to review`}
            </span>
          </div>
          <button className="icon-button" type="button" title="Close" onClick={onClose}>
            <X size={17} />
          </button>
        </header>

        <div className="duplicate-cluster-body">
        {exactCount > 0 && (
          <div className="duplicate-exact-bar">
            <span>
              <Zap size={15} /> {exactCount} exact {exactCount === 1 ? "match" : "matches"} (same
              file, Message-ID, or body)
            </span>
            <button
              className="save-button"
              type="button"
              disabled={busy}
              onClick={onResolveExact}
            >
              {busy ? "Working..." : "Auto-resolve exact"}
            </button>
          </div>
        )}

        {loading ? (
          <div className="duplicate-empty">Loading suspected duplicates...</div>
        ) : clusters.length === 0 ? (
          <div className="duplicate-empty">
            <CheckCircle2 size={20} />
            <p>No pending suspected duplicates in this case.</p>
          </div>
        ) : (
          <div className="duplicate-candidate-list">
            {clusters.map((cluster) => {
              const canonicalId = canonicalByCluster[cluster.id] ?? cluster.email_ids[0];
              const duplicateCount = cluster.email_ids.length - 1;
              return (
                <article className="duplicate-candidate" key={cluster.id}>
                  <div className="duplicate-candidate-header">
                    <div>
                      <strong>
                        {formatScore(cluster.max_score)} match | {cluster.email_ids.length} emails
                      </strong>
                      <span>{reasonSummary(cluster)}</span>
                    </div>
                    <Layers size={18} />
                  </div>
                  <div className="duplicate-cluster-members">
                    {cluster.emails.map((email) => (
                      <label
                        className={`duplicate-cluster-member ${
                          email.id === canonicalId ? "is-canonical" : ""
                        }`}
                        key={email.id}
                      >
                        <input
                          type="radio"
                          name={`canonical-${cluster.id}`}
                          checked={email.id === canonicalId}
                          onChange={() =>
                            setCanonicalByCluster((current) => ({
                              ...current,
                              [cluster.id]: email.id
                            }))
                          }
                        />
                        <ClusterEmail
                          email={email}
                          suggested={email.id === cluster.suggested_canonical_id}
                          timeZone={timeZone}
                        />
                      </label>
                    ))}
                  </div>
                  <div className="duplicate-actions">
                    <button
                      className="save-button"
                      type="button"
                      disabled={busy}
                      title="Keep the selected email and mark the rest as duplicates"
                      onClick={() => onResolveCluster(cluster, canonicalId)}
                    >
                      {busy
                        ? "Saving..."
                        : `Keep selected, mark ${duplicateCount} duplicate${
                            duplicateCount === 1 ? "" : "s"
                          }`}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
        </div>
      </section>
    </div>
  );
}

function ClusterEmail({
  email,
  suggested,
  timeZone
}: {
  email: EmailRecord;
  suggested: boolean;
  timeZone?: string;
}) {
  return (
    <div className="duplicate-preview">
      <div>
        <span>{email.source_kind}</span>
        <strong>{formatDate(email.date_utc, timeZone)}</strong>
      </div>
      <h3>{email.subject || "(no subject)"}</h3>
      <dl>
        <div>
          <dt>From</dt>
          <dd>{email.from_addr || "Unknown sender"}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>{email.source_file_display}</dd>
        </div>
      </dl>
      <p>{compactSnippet(email.body_text)}</p>
      {suggested && <small className="duplicate-suggested">Suggested to keep</small>}
    </div>
  );
}

function reasonSummary(cluster: DuplicateCluster) {
  const labels = new Set<string>();
  cluster.pairs.forEach((pair) => pair.reasons.forEach((reason) => labels.add(reason.label)));
  return Array.from(labels).join(" | ") || "Similar content";
}

function formatScore(value: number) {
  return `${Math.round(value * 100)}%`;
}

function compactSnippet(value: string) {
  const text = value.replace(/\s+/g, " ").trim();
  if (!text) return "No plain-text body captured.";
  return text.length > 160 ? `${text.slice(0, 160).trimEnd()}...` : text;
}

function formatDate(value?: string | null, timeZone?: string) {
  if (!value) return "No date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Invalid date";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone
  }).format(date);
}
