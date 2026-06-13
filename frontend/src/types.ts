export type CaseRecord = {
  id: number;
  public_id: string;
  name: string;
  created_at: string;
  updated_at: string;
  email_count: number;
  deleted_at?: string | null;
  default_tz?: string;
  has_cjk_content?: boolean;
};

export type AttachmentRecord = {
  id: number;
  email_id: number;
  filename: string;
  mime: string;
  size: number;
  content_id?: string | null;
  is_inline: boolean;
  created_at: string;
};

export type Tag = {
  id: number;
  case_id: number;
  name: string;
  color: string;
  created_at: string;
};

export type EmailRecord = {
  id: number;
  case_id: number;
  doc_id?: string | null;
  source_file_display: string;
  source_import_mode: string;
  source_openable: boolean;
  source_size?: number | null;
  source_mtime?: string | null;
  source_sha256?: string | null;
  ingest_job_id?: number | null;
  derived_from_attachment_id?: number | null;
  message_id?: string | null;
  in_reply_to?: string | null;
  references: string[];
  from_addr: string;
  to: string[];
  cc: string[];
  date_utc?: string | null;
  date_raw?: string | null;
  subject: string;
  body_text: string;
  body_html_raw: string;
  body_html_sanitized: string;
  body_format: string;
  thread_id?: string | null;
  parse_confidence: "high" | "med" | "low" | "failed";
  source_kind: string;
  parent_email_id?: number | null;
  chain_source_id?: number | null;
  chain_position: number;
  manual_chain_order?: number | null;
  manual_chrono_order?: number | null;
  chain_date_conflict: boolean;
  notes: string;
  important: boolean;
  user_edited: boolean;
  raw_json: Record<string, unknown>;
  created_at: string;
  deleted_at?: string | null;
  suspected_duplicate_count: number;
  flags: string[];
  attachments: AttachmentRecord[];
  tags: Tag[];
  boundary_method: string;
  boundary_evidence: string[];
  relation_confidence: "high" | "med" | "low";
  relation_thread_id: string;
  relation_parent_id?: number | null;
  relation_source_id: number;
  relation_refs: {
    message_id?: string | null;
    in_reply_to?: string | null;
    references: string[];
  };
};

export type EmailPage = {
  items: EmailRecord[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
};

export type RelationState = {
  active: boolean;
  focused: boolean;
  label: string;
  summary: string;
  confidence: "high" | "med" | "low";
};

export type IngestFileRecord = {
  id: number;
  job_id: number;
  source_file_display: string;
  status: string;
  email_id?: number | null;
  error?: string | null;
  warning_json: string[];
  source_import_mode: string;
  source_size?: number | null;
  source_mtime?: string | null;
  source_sha256?: string | null;
  doc_id?: string | null;
  created_at: string;
};

export type IngestJob = {
  id: number;
  case_id: number;
  status: string;
  total_files: number;
  processed_files: number;
  failed_files: number;
  started_at: string;
  finished_at?: string | null;
  contains_cjk?: boolean;
  files: IngestFileRecord[];
};

export type CaseFolder = {
  id: number;
  case_id: number;
  folder_path: string;
  recursive: boolean;
  last_scanned_at?: string | null;
  created_at: string;
};

export type EmailUpdate = Partial<{
  from_addr: string;
  to: string[];
  cc: string[];
  date_utc: string | null;
  subject: string;
  body_text: string;
  notes: string;
  important: boolean;
}>;

export type EmailCreate = {
  from_addr: string;
  to: string[];
  cc: string[];
  date_raw: string | null;
  subject: string;
  body_text: string;
  notes: string;
  important: boolean;
};

export type EmailSnipPartDraft = {
  part_index: number;
  source_segment?: string;
  from_addr: string;
  to: string[];
  cc: string[];
  date_raw?: string | null;
  subject: string;
  body_text: string;
  notes: string;
  important: boolean;
  parse_confidence?: string;
  flags?: string[];
  approved: boolean;
};

export type EmailSnipRequest = {
  split_offsets: number[];
  parts?: EmailSnipPartDraft[];
};

export type IngestMapRange = {
  start_offset: number;
  end_offset: number;
};

export type TextSpanMapping = {
  id: number;
  case_id: number;
  source_email_id: number;
  source_field: string;
  start_offset: number;
  end_offset: number;
  target_email_id: number;
  target_field: string;
  target_start_offset?: number | null;
  target_end_offset?: number | null;
  mapping_kind: "parsed" | "quoted" | "attached" | "snipped" | "manual" | "self" | "fuzzy";
  confidence: number;
  transform: string;
  created_by: string;
  stale: boolean;
  note: string;
  metadata?: Record<string, unknown>;
  color_index: number;
  target_subject: string;
  target_source: string;
};

export type IngestMapField = {
  field: string;
  label: string;
  text: string;
  length: number;
  coverage_percent: number;
  covered_chars: number;
  total_chars: number;
  unmapped_ranges: IngestMapRange[];
  mappings: TextSpanMapping[];
};

export type IngestMapSource = {
  email_id: number;
  source_file_display: string;
  subject: string;
  source_kind: string;
  superseded: boolean;
  coverage_percent: number;
  covered_chars: number;
  total_chars: number;
  mapping_count: number;
  inbound_mapping_count: number;
  mapping_role: "source" | "destination" | "source_and_destination" | "untracked";
  mapping_status: "mapped_source" | "created_from_source" | "unmapped" | "empty";
  fields: IngestMapField[];
};

export type IngestMapSummarySource = {
  email_id: number;
  source_file_display: string;
  subject: string;
  source_kind: string;
  superseded: boolean;
  coverage_percent: number;
  covered_chars: number;
  total_chars: number;
  mapping_count: number;
  mapping_counts: Record<string, number>;
  inbound_mapping_count: number;
  mapping_role: "source" | "destination" | "source_and_destination" | "untracked";
  mapping_status: "mapped_source" | "created_from_source" | "unmapped" | "empty";
};

export type IngestMapCard = {
  id: number;
  subject: string;
  from_addr: string;
  date_utc?: string | null;
  source_kind: string;
  source_file_display: string;
  color_index: number;
};

export type IngestMapStats = {
  source_count: number;
  target_count: number;
  coverage_percent: number;
  covered_chars: number;
  total_chars: number;
  unmapped_chars: number;
};

export type IngestMapSummary = {
  case_id: number;
  summary: IngestMapStats;
  sources: IngestMapSummarySource[];
};

export type IngestMapStatus = {
  case_id: number;
  ready: boolean;
  source_count: number;
  cached_source_count: number;
  mapped_source_count: number;
  running_jobs: number;
};

export type IngestMapDetail = {
  case_id: number;
  source_email_id?: number | null;
  summary: IngestMapStats;
  sources: IngestMapSource[];
  cards: IngestMapCard[];
};

export type IngestMap = IngestMapDetail;

export type SourceCardCreate = {
  source_field: string;
  start_offset: number;
  end_offset: number;
  subject?: string;
  notes?: string;
  important?: boolean;
};

export type SourceCardSelection = {
  source_email_id: number;
  source_field: string;
  start_offset: number;
  end_offset: number;
};

export type SourceCardGroupCreate = {
  selections: SourceCardSelection[];
  subject?: string;
  notes?: string;
  important?: boolean;
};

export type DuplicateReason = {
  code: string;
  label: string;
  value?: number;
};

export type DuplicateCandidate = {
  id: number;
  case_id: number;
  email_a_id: number;
  email_b_id: number;
  score: number;
  reasons: DuplicateReason[];
  status: "pending" | "duplicate" | "dissimilar";
  canonical_email_id?: number | null;
  duplicate_email_id?: number | null;
  created_at: string;
  updated_at: string;
  decided_at?: string | null;
  email_a?: EmailRecord | null;
  email_b?: EmailRecord | null;
};

export type DuplicateClusterPair = {
  email_a_id: number;
  email_b_id: number;
  score: number;
  reasons: DuplicateReason[];
};

export type DuplicateCluster = {
  id: string;
  email_ids: number[];
  candidate_ids: number[];
  max_score: number;
  suggested_canonical_id: number | null;
  emails: EmailRecord[];
  pairs: DuplicateClusterPair[];
};

export type AuditEvent = {
  id: number;
  case_id?: number | null;
  actor: string;
  action: string;
  entity_type: string;
  entity_id?: number | null;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
  created_at: string;
  prev_hash?: string | null;
  event_hash: string;
};
