import type {
  AuditEvent,
  CaseRecord,
  DuplicateCandidate,
  DuplicateCluster,
  EmailCreate,
  IngestMapDetail,
  IngestMapStatus,
  IngestMapSummary,
  EmailPage,
  EmailRecord,
  EmailSnipRequest,
  EmailSnipPartDraft,
  EmailUpdate,
  CaseFolder,
  IngestJob,
  SourceCardCreate,
  SourceCardGroupCreate,
  Tag
} from "../types";

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-EmailChrono-Local", "1");
  }
  const response = await fetch(url, {
    ...options,
    headers
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function listCases() {
  return request<CaseRecord[]>("/api/cases");
}

export function createCase(name: string, defaultTz?: string) {
  return request<CaseRecord>("/api/cases", {
    method: "POST",
    body: JSON.stringify({ name, default_tz: defaultTz })
  });
}

export function updateCase(caseId: number, payload: { name?: string; default_tz?: string }) {
  return request<CaseRecord>(`/api/cases/${caseId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteCase(caseId: number) {
  // Soft delete: moves the case to trash.
  return request<{ ok: boolean; trashed: boolean }>(`/api/cases/${caseId}`, {
    method: "DELETE"
  });
}

export function listTrash() {
  return request<CaseRecord[]>("/api/cases/trash");
}

export function restoreCase(caseId: number) {
  return request<{ ok: boolean }>(`/api/cases/${caseId}/restore`, { method: "POST" });
}

export function permanentlyDeleteCase(caseId: number, name: string) {
  return request<{ ok: boolean; deleted: boolean }>(
    `/api/cases/${caseId}/permanent-delete`,
    { method: "POST", body: JSON.stringify({ name }) }
  );
}

export function getCase(caseRef: number | string) {
  // Accepts the public_id (used in URLs) or the numeric id; the backend resolves both.
  return request<CaseRecord>(`/api/cases/${caseRef}`);
}

export function listAuditEvents(caseId: number) {
  return request<AuditEvent[]>(`/api/cases/${caseId}/audit`);
}

export function listEmails(
  caseId: number,
  filters: { q?: string; view?: "chrono" | "thread"; tagId?: number | null } = {}
) {
  const params = new URLSearchParams();
  if (filters.view) params.set("view", filters.view);
  if (filters.q) params.set("q", filters.q);
  if (filters.tagId) params.set("tag", String(filters.tagId));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<EmailRecord[]>(`/api/cases/${caseId}/emails${suffix}`);
}

export function listEmailsPage(
  caseId: number,
  filters: {
    q?: string;
    view?: "chrono" | "thread";
    tagId?: number | null;
    limit?: number;
    offset?: number;
  } = {}
) {
  const params = new URLSearchParams();
  if (filters.view) params.set("view", filters.view);
  if (filters.q) params.set("q", filters.q);
  if (filters.tagId) params.set("tag", String(filters.tagId));
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<EmailPage>(`/api/cases/${caseId}/emails/page${suffix}`);
}

export function listTags(caseId: number) {
  return request<Tag[]>(`/api/cases/${caseId}/tags`);
}

export function createTag(caseId: number, name: string, color?: string) {
  return request<Tag>(`/api/cases/${caseId}/tags`, {
    method: "POST",
    body: JSON.stringify({ name, color })
  });
}

export function updateTag(tagId: number, payload: { name?: string; color?: string }) {
  return request<Tag>(`/api/tags/${tagId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteTag(tagId: number) {
  return request<{ ok: boolean; deleted: boolean }>(`/api/tags/${tagId}`, {
    method: "DELETE"
  });
}

export function bulkTagEmails(
  caseId: number,
  emailIds: number[],
  tagIds: number[],
  attach: boolean
) {
  return request<{ ok: boolean; added?: number; removed?: number }>(
    `/api/cases/${caseId}/emails/tags`,
    {
      method: attach ? "POST" : "DELETE",
      body: JSON.stringify({ email_ids: emailIds, tag_ids: tagIds })
    }
  );
}

export function listEmailTrash(caseId: number) {
  return request<EmailRecord[]>(`/api/cases/${caseId}/emails/trash`);
}

export function listDuplicateCandidates(caseId: number, emailId?: number) {
  const params = new URLSearchParams();
  if (emailId) params.set("emailId", String(emailId));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<DuplicateCandidate[]>(`/api/cases/${caseId}/duplicate-candidates${suffix}`);
}

export function updateDuplicateCandidate(
  candidateId: number,
  payload: {
    status: "duplicate" | "dissimilar" | "pending";
    canonical_email_id?: number | null;
    duplicate_email_id?: number | null;
  }
) {
  return request<DuplicateCandidate>(`/api/duplicate-candidates/${candidateId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function listDuplicateClusters(caseId: number) {
  return request<DuplicateCluster[]>(`/api/cases/${caseId}/duplicate-clusters`);
}

export function resolveDuplicateCluster(
  caseId: number,
  canonicalEmailId: number,
  duplicateEmailIds: number[]
) {
  return request<{ ok: boolean; resolved: number }>(
    `/api/cases/${caseId}/duplicate-clusters/resolve`,
    {
      method: "POST",
      body: JSON.stringify({
        canonical_email_id: canonicalEmailId,
        duplicate_email_ids: duplicateEmailIds
      })
    }
  );
}

export function resolveExactDuplicates(caseId: number) {
  return request<{ ok: boolean; resolved: number }>(
    `/api/cases/${caseId}/duplicate-candidates/resolve-exact`,
    { method: "POST" }
  );
}

export function createEmail(caseId: number, payload: EmailCreate) {
  return request<EmailRecord>(`/api/cases/${caseId}/emails`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateEmail(emailId: number, payload: EmailUpdate) {
  return request<EmailRecord>(`/api/emails/${emailId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function snipEmail(emailId: number, payload: EmailSnipRequest) {
  return request<EmailRecord[]>(`/api/emails/${emailId}/snip`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function previewSnipEmail(emailId: number, payload: EmailSnipRequest) {
  return request<EmailSnipPartDraft[]>(`/api/emails/${emailId}/snip/preview`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getCaseIngestMap(caseId: number) {
  return request<IngestMapDetail>(`/api/cases/${caseId}/ingest-map`);
}

export function getCaseIngestMapSummary(caseId: number) {
  return request<IngestMapSummary>(`/api/cases/${caseId}/ingest-map-summary`);
}

export function getCaseIngestMapStatus(caseId: number) {
  return request<IngestMapStatus>(`/api/cases/${caseId}/ingest-map-status`);
}

export function getEmailIngestMap(emailId: number) {
  return request<IngestMapDetail>(`/api/emails/${emailId}/ingest-map`);
}

export function createCardFromSource(emailId: number, payload: SourceCardCreate) {
  return request<EmailRecord>(`/api/emails/${emailId}/create-card-from-source`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createCardFromSources(caseId: number, payload: SourceCardGroupCreate) {
  return request<EmailRecord>(`/api/cases/${caseId}/create-card-from-sources`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function deleteEmail(emailId: number) {
  return request<{ ok: boolean; trashed: boolean }>(`/api/emails/${emailId}`, {
    method: "DELETE"
  });
}

export function restoreEmail(emailId: number) {
  return request<EmailRecord>(`/api/emails/${emailId}/restore`, { method: "POST" });
}

export function updateChainOrder(caseId: number, emailIds: number[]) {
  return request<EmailRecord[]>(`/api/cases/${caseId}/chain-order`, {
    method: "PATCH",
    body: JSON.stringify({ email_ids: emailIds })
  });
}

export function updateChronologyOrder(caseId: number, emailIds: number[]) {
  return request<EmailRecord[]>(`/api/cases/${caseId}/email-order`, {
    method: "PATCH",
    body: JSON.stringify({ email_ids: emailIds })
  });
}

export function ingestFiles(
  caseId: number,
  files: File[],
  tagIds: number[] = [],
  containsCjk = false
) {
  const data = new FormData();
  files.forEach((file) => {
    const path = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
    data.append("files", file, path);
  });
  tagIds.forEach((tagId) => data.append("tag_ids", String(tagId)));
  data.append("contains_cjk", String(containsCjk));
  return request<IngestJob>(`/api/cases/${caseId}/ingest`, {
    method: "POST",
    body: data
  });
}

export function listIngestJobs(caseId: number) {
  return request<IngestJob[]>(`/api/cases/${caseId}/ingest`);
}

export function getIngestJob(caseId: number, jobId: number) {
  return request<IngestJob>(`/api/cases/${caseId}/ingest/${jobId}`);
}

export function ingestFolderPath(
  caseId: number,
  folderPath: string,
  recursive: boolean,
  tagIds: number[] = [],
  containsCjk = false
) {
  return request<IngestJob>(`/api/cases/${caseId}/ingest/folder`, {
    method: "POST",
    body: JSON.stringify({
      folder_path: folderPath,
      recursive,
      tag_ids: tagIds,
      contains_cjk: containsCjk
    })
  });
}

export function listTrackedFolders(caseId: number) {
  return request<CaseFolder[]>(`/api/cases/${caseId}/ingest/folders`);
}

export function refreshTrackedFolder(caseId: number, folderId: number) {
  return request<IngestJob>(`/api/cases/${caseId}/ingest/folder/${folderId}/refresh`, {
    method: "POST"
  });
}

export function openEmailSource(emailId: number) {
  return request<{ ok: boolean }>(`/api/emails/${emailId}/source/open`, {
    method: "POST"
  });
}

/** Stream the case export bundle (.ecz) and trigger a browser download. */
export async function exportCaseBundle(caseId: number, caseName?: string) {
  const response = await fetch(`/api/cases/${caseId}/export`);
  if (!response.ok) {
    throw new Error((await response.text()) || `Export failed: ${response.status}`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safe = (caseName ?? `case-${caseId}`).replace(/[^A-Za-z0-9 _-]/g, "").trim() || `case-${caseId}`;
  link.href = url;
  link.download = `${safe}.ecz`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export interface ImportPreview {
  format_version: number | null;
  schema_version: string | null;
  current_schema_version: string | null;
  case_name: string | null;
  counts: { emails: number; attachments: number; audit_events: number };
  compatible: boolean;
  refuse_reason: string | null;
}

export function importCasePreview(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<ImportPreview>("/api/import/preview", { method: "POST", body: form });
}

export function importCaseBundle(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<CaseRecord>("/api/import", { method: "POST", body: form });
}

export function relocateSources(caseId: number, newRoot: string) {
  return request<{ relinked: number }>(`/api/cases/${caseId}/relocate-sources`, {
    method: "POST",
    body: JSON.stringify({ new_root: newRoot })
  });
}
