type TimelineBucket = {
  key: string;
  label: string;
  count: number;
};

type Props = {
  buckets: TimelineBucket[];
  activeKey: string;
  total: number;
  onJump: (monthKey: string) => void;
};

export function TimelineNavigator({ buckets, activeKey, total, onJump }: Props) {
  if (!buckets.length) return null;
  const maxCount = Math.max(...buckets.map((bucket) => bucket.count), 1);

  return (
    <nav className="density-panel" aria-label="Timeline">
      <header>
        <h2>Timeline</h2>
        <small>
          {total} {total === 1 ? "email" : "emails"}
        </small>
      </header>
      <div className="density-list">
        {buckets.map((bucket) => {
          const width = Math.max((bucket.count / maxCount) * 100, 4);
          return (
            <button
              className={`density-item ${activeKey === bucket.key ? "active" : ""}`}
              key={bucket.key}
              onClick={() => onJump(bucket.key)}
              title={`Jump to ${bucket.label}`}
              type="button"
            >
              <span className="density-label">{bucket.label}</span>
              <span className="density-track">
                <span className="density-bar" style={{ width: `${width}%` }} />
              </span>
              <span className="density-count">{bucket.count}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
