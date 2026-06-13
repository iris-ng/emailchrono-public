import { Download, GripVertical, Plus, X } from "lucide-react";
import { useMemo, useState } from "react";
import type ExcelJS from "exceljs";
import type {
  EmailRecord,
  IngestMapDetail,
  IngestMapField,
  IngestMapRange,
  IngestMapSource,
  IngestMapSummary,
  SourceCardSelection,
  TextSpanMapping
} from "../types";

type Props = {
  summary: IngestMapSummary | null;
  detail: IngestMapDetail | null;
  selectedSourceId: number | null;
  loading: boolean;
  detailLoading: boolean;
  error: string;
  caseName: string;
  onSelectSource: (emailId: number) => void;
  onLoadDetail: (emailId: number) => Promise<IngestMapDetail>;
  onClose: () => void;
  onCreateCard: (
    source: IngestMapSource,
    field: IngestMapField,
    range: IngestMapRange
  ) => Promise<EmailRecord>;
  onCreateGroup: (
    selections: SourceCardSelection[],
    subject: string
  ) => Promise<EmailRecord>;
  onJumpToEmail: (emailId: number) => void;
};

type TraySelection = SourceCardSelection & {
  key: string;
  source_subject: string;
  field_label: string;
  text: string;
};

const MAP_COLORS = [
  "#2563eb",
  "#0f766e",
  "#b45309",
  "#7c3aed",
  "#be123c",
  "#0369a1",
  "#4d7c0f",
  "#c2410c",
  "#4338ca",
  "#0f766e",
  "#a21caf",
  "#52525b"
];

export function IngestMapDialog({
  summary,
  detail,
  selectedSourceId,
  loading,
  detailLoading,
  error,
  caseName,
  onSelectSource,
  onLoadDetail,
  onClose,
  onCreateCard,
  onCreateGroup,
  onJumpToEmail
}: Props) {
  const [savingKey, setSavingKey] = useState("");
  const [tray, setTray] = useState<TraySelection[]>([]);
  const [draggedKey, setDraggedKey] = useState<string | null>(null);
  const [groupSubject, setGroupSubject] = useState("");
  const activeSource = useMemo(() => {
    if (!detail?.sources.length) return null;
    return detail.sources[0];
  }, [detail]);

  async function createFromRange(source: IngestMapSource, field: IngestMapField, range: IngestMapRange) {
    const key = rangeKey(source, field, range, "create");
    setSavingKey(key);
    try {
      const created = await onCreateCard(source, field, range);
      onJumpToEmail(created.id);
    } finally {
      setSavingKey("");
    }
  }

  function toggleTrayRange(source: IngestMapSource, field: IngestMapField, range: IngestMapRange) {
    const key = rangeKey(source, field, range, "tray");
    setTray((current) => {
      if (current.some((item) => item.key === key)) {
        return current.filter((item) => item.key !== key);
      }
      return [
        ...current,
        {
          key,
          source_email_id: source.email_id,
          source_field: field.field,
          start_offset: range.start_offset,
          end_offset: range.end_offset,
          source_subject: source.subject,
          field_label: field.label,
          text: field.text.slice(range.start_offset, range.end_offset).trim()
        }
      ];
    });
  }

  function removeTrayItem(key: string) {
    setTray((current) => current.filter((item) => item.key !== key));
  }

  function moveTrayItem(sourceKey: string, targetKey: string) {
    if (sourceKey === targetKey) return;
    setTray((current) => {
      const from = current.findIndex((item) => item.key === sourceKey);
      const to = current.findIndex((item) => item.key === targetKey);
      if (from < 0 || to < 0) return current;
      const next = [...current];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }

  async function createGroupedCard() {
    if (!tray.length) return;
    setSavingKey("group");
    try {
      const created = await onCreateGroup(
        tray.map(({ source_email_id, source_field, start_offset, end_offset }) => ({
          source_email_id,
          source_field,
          start_offset,
          end_offset
        })),
        groupSubject.trim()
      );
      setTray([]);
      setGroupSubject("");
      onJumpToEmail(created.id);
    } finally {
      setSavingKey("");
    }
  }

  return (
    <div className="ingest-map-scrim" role="dialog" aria-modal="true" onClick={onClose}>
      <section className="ingest-map-dialog" onClick={(event) => event.stopPropagation()}>
        <header className="ingest-map-header">
          <div>
            <p className="eyebrow">Map</p>
            <h2>What went where</h2>
            <span>
              {summary
                ? `${summary.summary.coverage_percent}% covered across ${summary.summary.source_count} source emails`
                : "Loading source coverage"}
            </span>
          </div>
          <div className="ingest-map-header-actions">
            {summary && (
              <button type="button" onClick={() => void exportIngestMap(summary, caseName, onLoadDetail)}>
                <Download size={15} /> Map XLSX
              </button>
            )}
            <button className="icon-button" type="button" title="Close" onClick={onClose}>
              <X size={18} />
            </button>
          </div>
        </header>

        {loading && <div className="ingest-map-empty">Loading map...</div>}
        {error && <div className="ingest-map-error">{error}</div>}
        {!loading && summary && (
          <div className="ingest-map-layout">
            <aside className="ingest-map-source-list">
              <SummaryMeter percent={summary.summary.coverage_percent} />
              <div className="ingest-map-source-scroll">
                {summary.sources.map((source) => (
                  <button
                    type="button"
                    className={source.email_id === selectedSourceId ? "active" : ""}
                    key={source.email_id}
                    onClick={() => onSelectSource(source.email_id)}
                  >
                    <strong>{source.coverage_percent}%</strong>
                    <span>{source.subject}</span>
                    <small>
                      #{source.email_id} - {source.source_kind} - {statusLabel(source)}
                    </small>
                  </button>
                ))}
              </div>
            </aside>

            <main className="ingest-map-main">
              {detailLoading && <div className="ingest-map-empty">Loading source detail...</div>}
              {!detailLoading && activeSource && detail && (
                <section className="ingest-map-source-pane">
                  <div className="ingest-map-source-title">
                    <div>
                      <h3>{activeSource.subject}</h3>
                      <span>{activeSource.source_file_display}</span>
                    </div>
                    <strong>{activeSource.coverage_percent}% covered</strong>
                  </div>
                  {activeSource.fields.map((field) => (
                    <SourceFieldView
                      key={`${activeSource.email_id}-${field.field}`}
                      source={activeSource}
                      field={field}
                      savingKey={savingKey}
                      selectedRangeKeys={new Set(tray.map((item) => item.key))}
                      onCreate={createFromRange}
                      onToggleTray={toggleTrayRange}
                    />
                  ))}
                </section>
              )}
              {!detailLoading && !activeSource && (
                <div className="ingest-map-empty">Select a source email to inspect its mapped text.</div>
              )}

              <aside className="ingest-map-card-pane">
                <h3>Selection tray</h3>
                <div className="ingest-map-tray">
                  {!tray.length ? (
                    <div className="ingest-map-empty">Check source ranges to group them into one new card.</div>
                  ) : (
                    <>
                      <input
                        value={groupSubject}
                        onChange={(event) => setGroupSubject(event.target.value)}
                        placeholder="Grouped card subject"
                      />
                      <div className="ingest-map-tray-list">
                        {tray.map((item, index) => (
                          <article
                            key={item.key}
                            className={draggedKey === item.key ? "dragging" : ""}
                            draggable
                            onDragStart={(event) => {
                              setDraggedKey(item.key);
                              event.dataTransfer.effectAllowed = "move";
                            }}
                            onDragEnd={() => setDraggedKey(null)}
                            onDragOver={(event) => event.preventDefault()}
                            onDrop={(event) => {
                              event.preventDefault();
                              if (draggedKey) moveTrayItem(draggedKey, item.key);
                            }}
                          >
                            <span className="ingest-map-tray-grip" title="Drag to reorder">
                              <GripVertical size={14} />
                            </span>
                            <button type="button" title="Remove" onClick={() => removeTrayItem(item.key)}>
                              <X size={13} />
                            </button>
                            <strong>{index + 1}. #{item.source_email_id} {item.field_label}</strong>
                            <p>{item.text}</p>
                          </article>
                        ))}
                      </div>
                      <button
                        type="button"
                        disabled={savingKey === "group"}
                        onClick={() => void createGroupedCard()}
                      >
                        <Plus size={13} /> {savingKey === "group" ? "Creating..." : `Create grouped card (${tray.length})`}
                      </button>
                    </>
                  )}
                </div>
              </aside>
            </main>
          </div>
        )}
      </section>
    </div>
  );
}

function SummaryMeter({ percent }: { percent: number }) {
  return (
    <div className="ingest-map-meter">
      <div>
        <strong>{percent}%</strong>
        <span>Parsed text covered</span>
      </div>
      <i aria-hidden="true">
        <b style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
      </i>
    </div>
  );
}

function SourceFieldView({
  source,
  field,
  savingKey,
  selectedRangeKeys,
  onCreate,
  onToggleTray
}: {
  source: IngestMapSource;
  field: IngestMapField;
  savingKey: string;
  selectedRangeKeys: Set<string>;
  onCreate: (source: IngestMapSource, field: IngestMapField, range: IngestMapRange) => Promise<void>;
  onToggleTray: (source: IngestMapSource, field: IngestMapField, range: IngestMapRange) => void;
}) {
  const segments = sourceSegments(field.text, field.mappings);
  return (
    <article className="ingest-map-field">
      <header>
        <div>
          <strong>{field.label}</strong>
          <span>{field.coverage_percent}% covered</span>
        </div>
        <small>{field.covered_chars}/{field.total_chars} chars</small>
      </header>
      <pre>
        {segments.map((segment, index) =>
          segment.mapping ? (
            <mark
              key={`${segment.start}-${segment.end}-${index}`}
              className={`kind-${segment.mapping.mapping_kind}`}
              style={{
                backgroundColor: tintFor(segment.mapping.color_index),
                borderColor: colorFor(segment.mapping.color_index)
              }}
              title={`#${segment.mapping.target_email_id} ${segment.mapping.target_subject} (${segment.mapping.mapping_kind})`}
            >
              {segment.text}
            </mark>
          ) : (
            <span key={`${segment.start}-${segment.end}-${index}`}>{segment.text}</span>
          )
        )}
      </pre>
      {field.unmapped_ranges.length > 0 && (
        <div className="ingest-map-unmapped">
          <strong>Unmapped text</strong>
          {field.unmapped_ranges.slice(0, 6).map((range) => {
            const createKey = rangeKey(source, field, range, "create");
            return (
              <div className="ingest-map-gap" key={`${range.start_offset}-${range.end_offset}`}>
                <p>{field.text.slice(range.start_offset, range.end_offset).trim()}</p>
                <div>
                  <button
                    type="button"
                    className={selectedRangeKeys.has(rangeKey(source, field, range, "tray")) ? "active" : ""}
                    onClick={() => onToggleTray(source, field, range)}
                  >
                    {selectedRangeKeys.has(rangeKey(source, field, range, "tray")) ? "Added" : "Add"}
                  </button>
                  <button
                    type="button"
                    disabled={savingKey === createKey}
                    onClick={() => void onCreate(source, field, range)}
                  >
                    <Plus size={13} /> {savingKey === createKey ? "Creating..." : "Create card"}
                  </button>
                </div>
              </div>
            );
          })}
          {field.unmapped_ranges.length > 6 && (
            <small>{field.unmapped_ranges.length - 6} more unmapped ranges hidden in this field.</small>
          )}
        </div>
      )}
    </article>
  );
}

function sourceSegments(text: string, mappings: TextSpanMapping[]) {
  const ordered = [...mappings]
    .filter((mapping) => mapping.end_offset > mapping.start_offset)
    .sort((a, b) => a.start_offset - b.start_offset || rankKind(a.mapping_kind) - rankKind(b.mapping_kind));
  const segments: Array<{ start: number; end: number; text: string; mapping?: TextSpanMapping }> = [];
  let cursor = 0;
  ordered.forEach((mapping) => {
    const start = Math.max(cursor, Math.min(text.length, mapping.start_offset));
    const end = Math.max(start, Math.min(text.length, mapping.end_offset));
    if (start > cursor) {
      segments.push({ start: cursor, end: start, text: text.slice(cursor, start) });
    }
    if (end > start) {
      segments.push({ start, end, text: text.slice(start, end), mapping });
      cursor = end;
    }
  });
  if (cursor < text.length) segments.push({ start: cursor, end: text.length, text: text.slice(cursor) });
  return segments;
}

async function exportIngestMap(
  summary: IngestMapSummary,
  caseName: string,
  loadDetail: (emailId: number) => Promise<IngestMapDetail>
) {
  const details = await Promise.all(summary.sources.map((source) => loadDetail(source.email_id)));
  const map = combineDetails(summary, details);
  const Excel = await import("exceljs");
  const workbook = new Excel.Workbook();
  workbook.creator = "Chronology";
  workbook.created = new Date();

  addSummarySheet(workbook, summary);
  addSourceSheet(workbook, map);
  addCardSheet(workbook, map);
  addUnmappedSheet(workbook, map);

  const buffer = await workbook.xlsx.writeBuffer();
  const blob = new Blob([buffer], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${safeExportName(caseName)}-map.xlsx`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function combineDetails(summary: IngestMapSummary, details: IngestMapDetail[]): IngestMapDetail {
  const cardsById = new Map<number, IngestMapDetail["cards"][number]>();
  details.forEach((detail) => {
    detail.cards.forEach((card) => cardsById.set(card.id, card));
  });
  return {
    case_id: summary.case_id,
    source_email_id: null,
    summary: summary.summary,
    sources: details.flatMap((detail) => detail.sources),
    cards: Array.from(cardsById.values())
  };
}

function addSummarySheet(workbook: ExcelJS.Workbook, map: IngestMapSummary) {
  const sheet = workbook.addWorksheet("Coverage Summary", { views: [{ state: "frozen", ySplit: 1 }] });
  sheet.columns = [
    { header: "Email ID", width: 10 },
    { header: "Subject", width: 48 },
    { header: "Source", width: 42 },
    { header: "Kind", width: 14 },
    { header: "Coverage %", width: 14 },
    { header: "Covered chars", width: 14 },
    { header: "Total chars", width: 14 },
    { header: "Mappings", width: 12 },
    { header: "Superseded", width: 12 }
  ];
  map.sources.forEach((source) => {
    sheet.addRow([
      source.email_id,
      safeExcelText(source.subject),
      safeExcelText(source.source_file_display),
      source.source_kind,
      source.coverage_percent,
      source.covered_chars,
      source.total_chars,
      source.mapping_count,
      source.superseded ? "Yes" : "No"
    ]);
  });
  styleSheet(sheet);
}

function addSourceSheet(workbook: ExcelJS.Workbook, map: IngestMapDetail) {
  const sheet = workbook.addWorksheet("Source Map", { views: [{ state: "frozen", ySplit: 1 }] });
  sheet.columns = [
    { header: "Source email", width: 12 },
    { header: "Field", width: 16 },
    { header: "Coverage %", width: 12 },
    { header: "Mapped card IDs", width: 28 },
    { header: "Text", width: 100 }
  ];
  map.sources.forEach((source) => {
    source.fields.forEach((field) => {
      const row = sheet.addRow([
        source.email_id,
        field.label,
        field.coverage_percent,
        [...new Set(field.mappings.map((mapping) => `#${mapping.target_email_id}`))].join(", "),
        safeExcelText(field.text)
      ]);
      row.height = Math.min(160, Math.max(28, Math.ceil(field.text.length / 120) * 18));
      const firstMapping = field.mappings[0];
      if (firstMapping) {
        row.eachCell((cell) => {
          cell.fill = {
            type: "pattern",
            pattern: firstMapping.mapping_kind === "fuzzy" ? "lightTrellis" : "solid",
            fgColor: { argb: argbTint(firstMapping.color_index) }
          };
        });
      }
    });
  });
  styleSheet(sheet);
}

function addCardSheet(workbook: ExcelJS.Workbook, map: IngestMapDetail) {
  const sheet = workbook.addWorksheet("Card Map", { views: [{ state: "frozen", ySplit: 1 }] });
  sheet.columns = [
    { header: "Card ID", width: 10 },
    { header: "Subject", width: 50 },
    { header: "Source mappings", width: 80 },
    { header: "Kind", width: 14 },
    { header: "Source", width: 42 }
  ];
  map.cards.forEach((card) => {
    const mappings = map.sources.flatMap((source) =>
      source.fields.flatMap((field) =>
        field.mappings
          .filter((mapping) => mapping.target_email_id === card.id)
          .map((mapping) => `Email #${source.email_id} ${field.label} ${mapping.start_offset}-${mapping.end_offset} (${mapping.mapping_kind})`)
      )
    );
    const row = sheet.addRow([
      card.id,
      safeExcelText(card.subject),
      safeExcelText(mappings.join("; ")),
      card.source_kind,
      safeExcelText(card.source_file_display)
    ]);
    row.eachCell((cell) => {
      cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: argbTint(card.color_index) } };
    });
  });
  styleSheet(sheet);
}

function addUnmappedSheet(workbook: ExcelJS.Workbook, map: IngestMapDetail) {
  const sheet = workbook.addWorksheet("Unmapped Text", { views: [{ state: "frozen", ySplit: 1 }] });
  sheet.columns = [
    { header: "Email ID", width: 10 },
    { header: "Subject", width: 42 },
    { header: "Field", width: 16 },
    { header: "Offsets", width: 18 },
    { header: "Text", width: 100 }
  ];
  map.sources.forEach((source) => {
    source.fields.forEach((field) => {
      field.unmapped_ranges.forEach((range) => {
        sheet.addRow([
          source.email_id,
          safeExcelText(source.subject),
          field.label,
          `${range.start_offset}-${range.end_offset}`,
          safeExcelText(field.text.slice(range.start_offset, range.end_offset).trim())
        ]);
      });
    });
  });
  styleSheet(sheet);
}

function styleSheet(sheet: ExcelJS.Worksheet) {
  const header = sheet.getRow(1);
  header.eachCell((cell) => {
    cell.font = { bold: true, color: { argb: "FFFFFFFF" } };
    cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF1F2937" } };
    cell.alignment = { vertical: "middle", wrapText: true };
  });
  sheet.eachRow((row, rowNumber) => {
    if (rowNumber === 1) return;
    row.eachCell((cell) => {
      cell.alignment = { vertical: "top", wrapText: true };
      cell.border = {
        top: { style: "thin", color: { argb: "FFE5E7EB" } },
        left: { style: "thin", color: { argb: "FFE5E7EB" } },
        bottom: { style: "thin", color: { argb: "FFE5E7EB" } },
        right: { style: "thin", color: { argb: "FFE5E7EB" } }
      };
    });
  });
  sheet.autoFilter = {
    from: { row: 1, column: 1 },
    to: { row: 1, column: sheet.columnCount }
  };
}

function colorFor(index: number) {
  return MAP_COLORS[index % MAP_COLORS.length];
}

function tintFor(index: number) {
  return `${colorFor(index)}22`;
}

function argbTint(index: number) {
  return `33${colorFor(index).slice(1).toUpperCase()}`;
}

function rankKind(kind: TextSpanMapping["mapping_kind"]) {
  if (kind === "manual") return 0;
  if (kind === "snipped") return 1;
  if (kind === "quoted" || kind === "attached") return 2;
  if (kind === "parsed" || kind === "self") return 3;
  return 4;
}

function rangeKey(source: IngestMapSource, field: IngestMapField, range: IngestMapRange, action: string) {
  return `${action}:${source.email_id}:${field.field}:${range.start_offset}:${range.end_offset}`;
}

function statusLabel(source: {
  mapping_status: IngestMapSource["mapping_status"];
  inbound_mapping_count: number;
  mapping_count: number;
}) {
  if (source.mapping_status === "created_from_source") {
    return `destination - ${source.inbound_mapping_count} inbound`;
  }
  if (source.mapping_status === "mapped_source") {
    return `${source.mapping_count} outbound maps`;
  }
  if (source.mapping_status === "empty") return "empty source";
  return "unmapped source";
}

function safeExportName(value: string) {
  return (value || "chronology").replace(/[\\/:*?"<>|]+/g, "-").trim() || "chronology";
}

function safeExcelText(value: string) {
  return /^[=+\-@]/.test(value) ? `'${value}` : value;
}
