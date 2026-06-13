import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, CSSProperties, DragEvent, PointerEvent as ReactPointerEvent } from "react";
import type ExcelJS from "exceljs";
import {
  ArrowLeft,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Copy,
  Download,
  FileSearch,
  Globe,
  GripVertical,
  History,
  Inbox,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Tags,
  Trash2,
  Upload,
  X
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ThemeToggle } from "../App";
import {
  bulkTagEmails,
  createCardFromSource,
  createCardFromSources,
  createEmail,
  createTag,
  deleteEmail,
  deleteTag,
  getIngestJob,
  getCase,
  getCaseIngestMapStatus,
  getCaseIngestMapSummary,
  getEmailIngestMap,
  ingestFiles,
  ingestFolderPath,
  listDuplicateCandidates,
  listDuplicateClusters,
  resolveDuplicateCluster,
  resolveExactDuplicates,
  listAuditEvents,
  listEmailTrash,
  listEmailsPage,
  listTags,
  listTrackedFolders,
  refreshTrackedFolder,
  openEmailSource,
  exportCaseBundle,
  importCaseBundle,
  importCasePreview,
  relocateSources,
  previewSnipEmail,
  restoreEmail,
  snipEmail,
  updateCase,
  updateChainOrder,
  updateChronologyOrder,
  updateDuplicateCandidate,
  updateEmail,
  updateTag
} from "../api/client";
import { ChainOrderPanel } from "../components/ChainOrderPanel";
import { AuditTrailPanel, EmailTrashPanel } from "../components/CaseSidePanels";
import { DuplicateReviewDialog, otherDuplicateEmail } from "../components/DuplicateReviewDialog";
import { DuplicateClusterDialog } from "../components/DuplicateClusterDialog";
import { EmailCard } from "../components/EmailCard";
import { EmailDrawer } from "../components/EmailDrawer";
import { IngestMapDialog } from "../components/IngestMapDialog";
import { EmailSnipDialog } from "../components/EmailSnipDialog";
import { ManualEmailDrawer } from "../components/ManualEmailDrawer";
import { TagManager } from "../components/TagManager";
import { TimelineNavigator } from "../components/TimelineNavigator";
import { UploadDropzone } from "../components/UploadDropzone";
import { UnifiedFilterBox } from "../components/UnifiedFilterBox";
import { useElementWidth } from "../hooks/useElementWidth";
import type {
  AuditEvent,
  CaseFolder,
  CaseRecord,
  DuplicateCandidate,
  DuplicateCluster,
  EmailCreate,
  EmailRecord,
  EmailSnipPartDraft,
  EmailUpdate,
  IngestMapDetail,
  IngestMapField,
  IngestMapRange,
  IngestMapSource,
  IngestMapStatus,
  IngestMapSummary,
  IngestJob,
  SourceCardSelection,
  Tag
} from "../types";
import {
  buildRelationStates,
  compareForChainDisplay,
  relatedChainEmails,
  threadKey
} from "../utils/relationFocus";

type ViewMode = "chrono" | "thread";
type DropPosition = "before" | "after";
const EMAIL_PAGE_SIZE = 100;

const SIDEBAR_WIDTH_KEY = "emailchrono.sidebarWidth";
const SIDEBAR_COLLAPSED_KEY = "emailchrono.sidebarCollapsed";
const SIDEBAR_MIN_WIDTH = 240;
const SIDEBAR_MAX_WIDTH = 460;
const SIDEBAR_DEFAULT_WIDTH = 300;
// Below this panel width the toolbar buttons drop their text labels and show icons only.
const TOOLBAR_ICONS_ONLY_WIDTH = 640;

function clampSidebarWidth(value: number) {
  return Math.max(SIDEBAR_MIN_WIDTH, Math.min(value, SIDEBAR_MAX_WIDTH));
}

function readStoredSidebarWidth() {
  try {
    const raw = window.localStorage.getItem(SIDEBAR_WIDTH_KEY);
    if (!raw) return SIDEBAR_DEFAULT_WIDTH;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) ? clampSidebarWidth(parsed) : SIDEBAR_DEFAULT_WIDTH;
  } catch {
    return SIDEBAR_DEFAULT_WIDTH;
  }
}

function readStoredSidebarCollapsed() {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

type EmailMonthGroup = {
  key: string;
  label: string;
  count: number;
  emails: EmailRecord[];
};

export function CasePage() {
  const { caseRef = "" } = useParams();
  const navigate = useNavigate();
  // The URL carries the stable public_id; resolve it once to the internal numeric
  // id, which all case-scoped API calls below use. 0 means "not resolved yet".
  const [numericCaseId, setNumericCaseId] = useState(0);
  const [importing, setImporting] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);
  const [caseRecord, setCaseRecord] = useState<CaseRecord | null>(null);
  const [emails, setEmails] = useState<EmailRecord[]>([]);
  const [emailTotal, setEmailTotal] = useState(0);
  const [hasMoreEmails, setHasMoreEmails] = useState(false);
  const [emailTrash, setEmailTrash] = useState<EmailRecord[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [selected, setSelected] = useState<EmailRecord | null>(null);
  const [chainPanelEmail, setChainPanelEmail] = useState<EmailRecord | null>(null);
  const [duplicateReviewEmail, setDuplicateReviewEmail] = useState<EmailRecord | null>(null);
  const [duplicateCandidates, setDuplicateCandidates] = useState<DuplicateCandidate[]>([]);
  const [duplicateLoading, setDuplicateLoading] = useState(false);
  const [duplicateSavingId, setDuplicateSavingId] = useState<number | null>(null);
  const [clusterReviewOpen, setClusterReviewOpen] = useState(false);
  const [duplicateClusters, setDuplicateClusters] = useState<DuplicateCluster[]>([]);
  const [clusterLoading, setClusterLoading] = useState(false);
  const [clusterBusy, setClusterBusy] = useState(false);
  const [manualDrawerOpen, setManualDrawerOpen] = useState(false);
  const [snipEmailRecord, setSnipEmailRecord] = useState<EmailRecord | null>(null);
  const [snipSaving, setSnipSaving] = useState(false);
  const [ingestMapOpen, setIngestMapOpen] = useState(false);
  const [ingestMapSummary, setIngestMapSummary] = useState<IngestMapSummary | null>(null);
  const [ingestMapDetail, setIngestMapDetail] = useState<IngestMapDetail | null>(null);
  const [ingestMapEmailId, setIngestMapEmailId] = useState<number | null>(null);
  const [ingestMapLoading, setIngestMapLoading] = useState(false);
  const [ingestMapDetailLoading, setIngestMapDetailLoading] = useState(false);
  const [ingestMapError, setIngestMapError] = useState("");
  const [ingestMapStatus, setIngestMapStatus] = useState<IngestMapStatus | null>(null);
  const [ingestMapStatusLoading, setIngestMapStatusLoading] = useState(false);
  const [emailTrashOpen, setEmailTrashOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [jobPanelOpen, setJobPanelOpen] = useState(false);
  const [job, setJob] = useState<IngestJob | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => readStoredSidebarWidth());
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => readStoredSidebarCollapsed());
  const sidebarResizeStart = useRef<{ x: number; width: number } | null>(null);
  const [toolbarRef, toolbarWidth] = useElementWidth<HTMLDivElement>();
  const toolbarIconsOnly = toolbarWidth > 0 && toolbarWidth < TOOLBAR_ICONS_ONLY_WIDTH;
  const [folders, setFolders] = useState<CaseFolder[]>([]);
  const [refreshingFolderId, setRefreshingFolderId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [tags, setTags] = useState<Tag[]>([]);
  const [tagFilterId, setTagFilterId] = useState<number | null>(null);
  const [tagManagerOpen, setTagManagerOpen] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("chrono");
  const [rearrangeMode, setRearrangeMode] = useState(false);
  const [reorderItems, setReorderItems] = useState<EmailRecord[]>([]);
  const [draggedReorderId, setDraggedReorderId] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<{ id: number; position: DropPosition } | null>(null);
  const [savingReorder, setSavingReorder] = useState(false);
  const [activeMonthKey, setActiveMonthKey] = useState("");
  const [pendingMonthKey, setPendingMonthKey] = useState("");
  const [flashEmailId, setFlashEmailId] = useState<number | null>(null);
  const flashTimer = useRef<number | null>(null);
  useEffect(() => () => {
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
  }, []);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  // Surface ingest progress automatically while a job is running; otherwise it
  // stays collapsed like the other activity cards until the user opens it.
  useEffect(() => {
    if (job?.status === "running") setJobPanelOpen(true);
  }, [job?.status]);

  function startSidebarResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    sidebarResizeStart.current = { x: event.clientX, width: sidebarWidth };
    event.currentTarget.setPointerCapture(event.pointerId);
    document.body.classList.add("sidebar-resizing");
  }

  function onSidebarResizeMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!sidebarResizeStart.current) return;
    // Sidebar is left-docked, so dragging right (larger clientX) grows it.
    const delta = event.clientX - sidebarResizeStart.current.x;
    setSidebarWidth(clampSidebarWidth(sidebarResizeStart.current.width + delta));
  }

  function endSidebarResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (!sidebarResizeStart.current) return;
    sidebarResizeStart.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    document.body.classList.remove("sidebar-resizing");
    try {
      window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(Math.round(sidebarWidth)));
    } catch {
      // ignore persistence failures (private mode, etc.)
    }
  }

  function setSidebarCollapsedPersisted(collapsed: boolean) {
    setSidebarCollapsed(collapsed);
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // ignore persistence failures (private mode, etc.)
    }
  }

  async function refresh(searchQuery = query, activeTagId = tagFilterId) {
    if (!numericCaseId) return;
    setLoading(true);
    setError("");
    try {
      const [loadedCase, loadedPage, loadedTrash, loadedAudit, loadedTags] = await Promise.all([
        getCase(numericCaseId),
        listEmailsPage(numericCaseId, {
          q: searchQuery,
          view: viewMode,
          tagId: activeTagId,
          limit: EMAIL_PAGE_SIZE,
          offset: 0
        }),
        listEmailTrash(numericCaseId),
        listAuditEvents(numericCaseId),
        listTags(numericCaseId)
      ]);
      setCaseRecord(loadedCase);
      setEmails(loadedPage.items);
      setEmailTotal(loadedPage.total);
      setHasMoreEmails(loadedPage.has_more);
      setEmailTrash(loadedTrash);
      setAuditEvents(loadedAudit);
      setTags(loadedTags);
      setSelected((current) =>
        current ? loadedPage.items.find((email) => email.id === current.id) ?? null : null
      );
      setChainPanelEmail((current) =>
        current ? loadedPage.items.find((email) => email.id === current.id) ?? null : null
      );
      setDuplicateReviewEmail((current) =>
        current ? loadedPage.items.find((email) => email.id === current.id) ?? null : null
      );
      setSnipEmailRecord((current) =>
        current ? loadedPage.items.find((email) => email.id === current.id) ?? null : null
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load case");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setNumericCaseId(0);
    setLoading(true);
    getCase(caseRef)
      .then((rec) => {
        if (!cancelled) setNumericCaseId(rec.id);
      })
      .catch(() => {
        if (cancelled) return;
        setError("Case not found");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [caseRef]);

  useEffect(() => {
    if (!numericCaseId) return;
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numericCaseId, viewMode, tagFilterId]);

  useEffect(() => {
    void refreshMapStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numericCaseId, job?.status]);

  const displayEmails = useMemo(() => [...emails].sort(compareForDisplay), [emails]);
  const monthGroups = useMemo(
    () => groupEmailMonths(displayEmails, caseRecord?.default_tz),
    [displayEmails, caseRecord?.default_tz]
  );
  const threadGroups = useMemo(
    () => groupThreads(emails, caseRecord?.default_tz),
    [emails, caseRecord?.default_tz]
  );
  const chainPanelEmails = useMemo(
    () => relatedChainEmails(displayEmails, chainPanelEmail),
    [displayEmails, chainPanelEmail]
  );
  // The chain panel is the single source of truth: opening it both shows the
  // sidebar and drives the chronology highlight overlay below.
  const relationFocus = useMemo(
    () =>
      chainPanelEmail
        ? displayEmails.find((email) => email.id === chainPanelEmail.id) ?? chainPanelEmail
        : null,
    [displayEmails, chainPanelEmail]
  );
  const relationStates = useMemo(
    () => buildRelationStates(displayEmails, relationFocus),
    [displayEmails, relationFocus]
  );
  const exactDuplicateCount = useMemo(() => {
    const exactCodes = new Set(["same_source_sha256", "same_message_id", "same_body_hash"]);
    let count = 0;
    duplicateClusters.forEach((cluster) =>
      cluster.pairs.forEach((pair) => {
        if (pair.reasons.some((reason) => exactCodes.has(reason.code))) count += 1;
      })
    );
    return count;
  }, [duplicateClusters]);

  useEffect(() => {
    if (!monthGroups.length) {
      setActiveMonthKey("");
      return;
    }
    setActiveMonthKey((current) =>
      current && monthGroups.some((group) => group.key === current) ? current : monthGroups[0].key
    );
  }, [monthGroups]);

  useEffect(() => {
    if (viewMode !== "chrono" || !monthGroups.length) return;
    const markers = Array.from(document.querySelectorAll<HTMLElement>(".month-marker[data-month-key]"));
    if (!markers.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => Math.abs(a.boundingClientRect.top) - Math.abs(b.boundingClientRect.top))[0];
        const key = visible?.target.getAttribute("data-month-key");
        if (key) setActiveMonthKey(key);
      },
      { rootMargin: "-110px 0px -70% 0px", threshold: [0.1, 0.4, 0.8] }
    );

    markers.forEach((marker) => observer.observe(marker));
    return () => observer.disconnect();
  }, [monthGroups, viewMode]);

  useEffect(() => {
    if (!pendingMonthKey || viewMode !== "chrono" || loading) return;
    scrollToMonth(pendingMonthKey);
    setPendingMonthKey("");
  }, [loading, monthGroups, pendingMonthKey, viewMode]);

  useEffect(() => {
    if (!numericCaseId || job?.status !== "running") return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const latest = await getIngestJob(numericCaseId, job.id);
          if (cancelled) return;
          setJob(latest);
          if (latest.status !== "running") {
            window.clearInterval(timer);
            await refresh();
            await refreshMapStatus();
            void loadFolders();
          }
        } catch (err) {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : "Ingest progress could not be loaded");
          }
        }
      })();
    }, 900);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numericCaseId, job?.id, job?.status]);

  useEffect(() => {
    void loadFolders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numericCaseId]);

  async function loadMoreEmails() {
    if (!numericCaseId || loadingMore || !hasMoreEmails) return;
    setLoadingMore(true);
    setError("");
    try {
      const page = await listEmailsPage(numericCaseId, {
        q: query,
        view: viewMode,
        tagId: tagFilterId,
        limit: EMAIL_PAGE_SIZE,
        offset: emails.length
      });
      setEmails((current) => mergeEmails(current, page.items));
      setEmailTotal(page.total);
      setHasMoreEmails(page.has_more);
    } catch (err) {
      setError(err instanceof Error ? err.message : "More emails could not be loaded");
    } finally {
      setLoadingMore(false);
    }
  }

  async function onUpload(files: File[], tagIds: number[], containsCjk: boolean) {
    setError("");
    try {
      const result = await ingestFiles(numericCaseId, files, tagIds, containsCjk);
      setJob(result);
      if (result.status !== "running") await refresh();
      void refreshMapStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to ingest files");
    }
  }

  async function onFolderImport(
    folderPath: string,
    recursive: boolean,
    tagIds: number[],
    containsCjk: boolean
  ) {
    setError("");
    try {
      const result = await ingestFolderPath(numericCaseId, folderPath, recursive, tagIds, containsCjk);
      setJob(result);
      if (result.status !== "running") await refresh();
      void loadFolders();
      void refreshMapStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import folder");
    }
  }

  async function loadFolders() {
    if (!numericCaseId) return;
    try {
      setFolders(await listTrackedFolders(numericCaseId));
    } catch {
      // Tracked folders are a convenience; ignore load failures silently.
    }
  }

  async function onRefreshFolder(folderId: number) {
    setError("");
    setRefreshingFolderId(folderId);
    try {
      const result = await refreshTrackedFolder(numericCaseId, folderId);
      setJob(result);
      if (result.status !== "running") await refresh();
      void loadFolders();
      void refreshMapStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh folder");
    } finally {
      setRefreshingFolderId(null);
    }
  }

  function applyTagChange(emailIds: number[], tag: Tag, attach: boolean) {
    // Optimistically reflect a tag add/remove on the affected cards without a
    // full reload. The persisted source of truth is the email_tags table.
    const ids = new Set(emailIds);
    setEmails((current) =>
      current.map((email) => {
        if (!ids.has(email.id)) return email;
        const without = email.tags.filter((existing) => existing.id !== tag.id);
        return { ...email, tags: attach ? [...without, tag] : without };
      })
    );
  }

  async function onAddTagToEmail(emailId: number, tagId: number) {
    const tag = tags.find((item) => item.id === tagId);
    if (!tag) return;
    setError("");
    try {
      await bulkTagEmails(numericCaseId, [emailId], [tagId], true);
      applyTagChange([emailId], tag, true);
      await refreshAudit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add tag");
    }
  }

  async function onRemoveTagFromEmail(emailId: number, tagId: number) {
    const tag = tags.find((item) => item.id === tagId);
    if (!tag) return;
    setError("");
    try {
      await bulkTagEmails(numericCaseId, [emailId], [tagId], false);
      applyTagChange([emailId], tag, false);
      await refreshAudit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove tag");
    }
  }

  async function onCreateTag(name: string, color?: string): Promise<Tag | null> {
    setError("");
    try {
      const tag = await createTag(numericCaseId, name, color);
      setTags((current) =>
        current.some((item) => item.id === tag.id)
          ? current.map((item) => (item.id === tag.id ? tag : item))
          : [...current, tag].sort((a, b) => a.name.localeCompare(b.name))
      );
      await refreshAudit();
      return tag;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create tag");
      return null;
    }
  }

  async function onCreateTagForEmail(emailId: number, name: string) {
    const tag = await onCreateTag(name);
    if (tag) await onAddTagToEmail(emailId, tag.id);
  }

  async function onUpdateTag(tagId: number, payload: { name?: string; color?: string }) {
    setError("");
    try {
      const updated = await updateTag(tagId, payload);
      setTags((current) => current.map((item) => (item.id === tagId ? updated : item)));
      // Reflect the new name/color on any cards already showing the tag.
      setEmails((current) =>
        current.map((email) => ({
          ...email,
          tags: email.tags.map((tag) => (tag.id === tagId ? updated : tag))
        }))
      );
      await refreshAudit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update tag");
    }
  }

  async function onDeleteTag(tagId: number) {
    setError("");
    try {
      await deleteTag(tagId);
      setTags((current) => current.filter((item) => item.id !== tagId));
      setEmails((current) =>
        current.map((email) => ({
          ...email,
          tags: email.tags.filter((tag) => tag.id !== tagId)
        }))
      );
      if (tagFilterId === tagId) setTagFilterId(null);
      await refreshAudit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete tag");
    }
  }

  async function onOpenSource(emailId: number) {
    setError("");
    try {
      await openEmailSource(emailId);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to open source file";
      // The backend returns 409 with reason "source_moved" when the original
      // file can't be found; offer to re-link by locating the evidence folder.
      if (message.includes("source_moved") && numericCaseId) {
        const newRoot = window.prompt(
          "The original source file could not be found. Enter the folder where the evidence files now live to re-link them:"
        );
        if (newRoot && newRoot.trim()) {
          try {
            const { relinked } = await relocateSources(numericCaseId, newRoot.trim());
            if (relinked > 0) {
              await openEmailSource(emailId);
              return;
            }
            setError("No matching source files were found in that folder.");
          } catch (relErr) {
            setError(relErr instanceof Error ? relErr.message : "Failed to relocate sources");
          }
        }
        return;
      }
      setError(message);
    }
  }

  async function refreshEmailTrash() {
    if (!numericCaseId) return;
    const trashed = await listEmailTrash(numericCaseId);
    setEmailTrash(trashed);
  }

  async function refreshAudit() {
    if (!numericCaseId) return;
    const events = await listAuditEvents(numericCaseId);
    setAuditEvents(events);
  }

  async function onDeleteEmail(emailId: number) {
    setError("");
    try {
      await deleteEmail(emailId);
      setEmails((current) => current.filter((email) => email.id !== emailId));
      setSelected((current) => (current?.id === emailId ? null : current));
      setChainPanelEmail((current) => (current?.id === emailId ? null : current));
      setCaseRecord((current) =>
        current ? { ...current, email_count: Math.max(0, current.email_count - 1) } : current
      );
      setEmailTotal((current) => Math.max(0, current - 1));
      await Promise.all([refreshEmailTrash(), refreshAudit()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Email could not be moved to trash");
    }
  }

  async function onRestoreEmail(emailId: number) {
    setError("");
    try {
      await restoreEmail(emailId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Email could not be restored");
    }
  }

  async function onSave(emailId: number, update: EmailUpdate) {
    const saved = await updateEmail(emailId, update);
    setEmails((current) => current.map((email) => (email.id === emailId ? saved : email)));
    setSelected(saved);
    await refreshAudit();
  }

  async function onCreateManualEmail(payload: EmailCreate) {
    const created = await createEmail(numericCaseId, payload);
    setEmails((current) => [
      ...current.filter((email) => email.id !== created.id),
      created
    ]);
    setSelected(created);
    setCaseRecord((current) =>
      current ? { ...current, email_count: current.email_count + 1 } : current
    );
    setEmailTotal((current) => current + 1);
    await refreshAudit();
    return created;
  }

  async function onSaveEmailAnnotation(emailId: number, update: Pick<EmailUpdate, "notes" | "important">) {
    const saved = await updateEmail(emailId, update);
    setEmails((current) => current.map((email) => (email.id === emailId ? saved : email)));
    setSelected((current) => (current?.id === emailId ? saved : current));
    setChainPanelEmail((current) => (current?.id === emailId ? saved : current));
    await refreshAudit();
  }

  async function onSaveChainOrder(emailIds: number[]) {
    const saved = await updateChainOrder(numericCaseId, emailIds);
    setEmails((current) =>
      current.map((email) => saved.find((savedEmail) => savedEmail.id === email.id) ?? email)
    );
    await refreshAudit();
  }

  async function submitSearch() {
    const nextQuery = searchDraft.trim();
    setQuery(nextQuery);
    await refresh(nextQuery);
  }

  async function clearFilters() {
    setSearchDraft("");
    setQuery("");
    setTagFilterId(null);
    await refresh("", null);
  }

  async function onApplySnip(emailId: number, splitOffsets: number[], parts: EmailSnipPartDraft[]) {
    setSnipSaving(true);
    setError("");
    try {
      const created = await snipEmail(emailId, { split_offsets: splitOffsets, parts });
      setSnipEmailRecord(null);
      setSelected(created[0] ?? null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Snip could not be applied");
    } finally {
      setSnipSaving(false);
    }
  }

  async function openCaseIngestMap() {
    if (!mapReady) return;
    setIngestMapOpen(true);
    setIngestMapEmailId(null);
    setIngestMapLoading(true);
    setIngestMapDetailLoading(false);
    setIngestMapError("");
    setIngestMapSummary(null);
    setIngestMapDetail(null);
    try {
      const summary = await getCaseIngestMapSummary(numericCaseId);
      setIngestMapSummary(summary);
      const firstSourceId = summary.sources[0]?.email_id ?? null;
      if (firstSourceId) {
        setIngestMapEmailId(firstSourceId);
        void loadIngestMapDetail(firstSourceId);
      }
    } catch (err) {
      setIngestMapError(err instanceof Error ? err.message : "Map could not be loaded");
    } finally {
      setIngestMapLoading(false);
    }
  }

  async function openEmailIngestMap(emailId: number) {
    if (!mapReady) return;
    setIngestMapOpen(true);
    setIngestMapEmailId(emailId);
    setIngestMapLoading(true);
    setIngestMapDetailLoading(true);
    setIngestMapError("");
    setIngestMapSummary(null);
    setIngestMapDetail(null);
    try {
      const [summary, detail] = await Promise.all([
        getCaseIngestMapSummary(numericCaseId),
        getEmailIngestMap(emailId)
      ]);
      setIngestMapSummary(summary);
      setIngestMapDetail(detail);
    } catch (err) {
      setIngestMapError(err instanceof Error ? err.message : "Email map could not be loaded");
    } finally {
      setIngestMapLoading(false);
      setIngestMapDetailLoading(false);
    }
  }

  async function loadIngestMapDetail(emailId: number) {
    setIngestMapEmailId(emailId);
    setIngestMapDetailLoading(true);
    setIngestMapError("");
    try {
      setIngestMapDetail(await getEmailIngestMap(emailId));
    } catch (err) {
      setIngestMapError(err instanceof Error ? err.message : "Email map could not be loaded");
    } finally {
      setIngestMapDetailLoading(false);
    }
  }

  async function refreshIngestMap(emailId = ingestMapEmailId) {
    if (!ingestMapOpen) return;
    setIngestMapLoading(true);
    setIngestMapDetailLoading(Boolean(emailId));
    setIngestMapError("");
    try {
      const [summary, detail] = await Promise.all([
        getCaseIngestMapSummary(numericCaseId),
        emailId ? getEmailIngestMap(emailId) : Promise.resolve(null)
      ]);
      setIngestMapSummary(summary);
      setIngestMapDetail(detail);
    } catch (err) {
      setIngestMapError(err instanceof Error ? err.message : "Map could not be refreshed");
    } finally {
      setIngestMapLoading(false);
      setIngestMapDetailLoading(false);
    }
  }

  async function refreshMapStatus() {
    if (!numericCaseId) return;
    setIngestMapStatusLoading(true);
    try {
      setIngestMapStatus(await getCaseIngestMapStatus(numericCaseId));
    } catch {
      setIngestMapStatus(null);
    } finally {
      setIngestMapStatusLoading(false);
    }
  }

  async function onCreateCardFromMap(
    source: IngestMapSource,
    field: IngestMapField,
    range: IngestMapRange
  ) {
    const text = field.text.slice(range.start_offset, range.end_offset).trim();
    const created = await createCardFromSource(source.email_id, {
      source_field: field.field,
      start_offset: range.start_offset,
      end_offset: range.end_offset,
      subject: `${field.label} selection from #${source.email_id}`,
      notes: text.length > 240 ? `${text.slice(0, 240)}...` : text
    });
    await refresh();
    await refreshIngestMap(source.email_id);
    return created;
  }

  async function onCreateGroupedCardFromMap(selections: SourceCardSelection[], subject: string) {
    const created = await createCardFromSources(numericCaseId, {
      selections,
      subject: subject || `Grouped source selection (${selections.length})`,
      notes: `${selections.length} source ranges grouped from the map`
    });
    await refresh();
    await refreshIngestMap(created.parent_email_id ?? ingestMapEmailId);
    return created;
  }

  async function openDuplicateReview(email: EmailRecord) {
    setDuplicateReviewEmail(email);
    setDuplicateLoading(true);
    setError("");
    try {
      const candidates = await listDuplicateCandidates(numericCaseId, email.id);
      setDuplicateCandidates(candidates);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Duplicate candidates could not be loaded");
      setDuplicateReviewEmail(null);
      setDuplicateCandidates([]);
    } finally {
      setDuplicateLoading(false);
    }
  }

  async function decideDuplicateCandidate(
    candidate: DuplicateCandidate,
    status: "duplicate" | "dissimilar",
    duplicateEmailId?: number
  ) {
    if (!duplicateReviewEmail) return;
    const other = otherDuplicateEmail(candidate, duplicateReviewEmail.id);
    if (!other) return;
    setDuplicateSavingId(candidate.id);
    setError("");
    try {
      const payload =
        status === "duplicate"
          ? {
              status,
              canonical_email_id:
                duplicateEmailId === duplicateReviewEmail.id ? other.id : duplicateReviewEmail.id,
              duplicate_email_id: duplicateEmailId
            }
          : { status };
      await updateDuplicateCandidate(candidate.id, payload);
      setDuplicateCandidates((current) => current.filter((item) => item.id !== candidate.id));
      const affected = [candidate.email_a_id, candidate.email_b_id];
      setEmails((current) =>
        current.map((email) =>
          affected.includes(email.id)
            ? {
                ...email,
                suspected_duplicate_count: Math.max(0, email.suspected_duplicate_count - 1)
              }
            : email
        )
      );
      await refreshAudit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Duplicate decision could not be saved");
    } finally {
      setDuplicateSavingId(null);
    }
  }

  async function loadDuplicateClusters() {
    setClusterLoading(true);
    try {
      const clusters = await listDuplicateClusters(numericCaseId);
      setDuplicateClusters(clusters);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Duplicate clusters could not be loaded");
      setDuplicateClusters([]);
    } finally {
      setClusterLoading(false);
    }
  }

  async function openClusterReview() {
    setClusterReviewOpen(true);
    setError("");
    await loadDuplicateClusters();
  }

  async function onResolveCluster(cluster: DuplicateCluster, canonicalId: number) {
    const duplicateIds = cluster.email_ids.filter((id) => id !== canonicalId);
    if (!duplicateIds.length) return;
    setClusterBusy(true);
    setError("");
    try {
      await resolveDuplicateCluster(numericCaseId, canonicalId, duplicateIds);
      await Promise.all([loadDuplicateClusters(), refresh()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cluster could not be resolved");
    } finally {
      setClusterBusy(false);
    }
  }

  async function onResolveExactDuplicates() {
    setClusterBusy(true);
    setError("");
    try {
      await resolveExactDuplicates(numericCaseId);
      await Promise.all([loadDuplicateClusters(), refresh()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Exact duplicates could not be resolved");
    } finally {
      setClusterBusy(false);
    }
  }

  function startRearrangeMode() {
    setError("");
    setReorderItems(displayEmails);
    setDraggedReorderId(null);
    setDropTarget(null);
    setRearrangeMode(true);
  }

  function cancelRearrangeMode() {
    setRearrangeMode(false);
    setReorderItems([]);
    setDraggedReorderId(null);
    setDropTarget(null);
  }

  function moveReorderEmail(sourceId: number, targetId: number, position: DropPosition) {
    if (sourceId === targetId) {
      setDropTarget(null);
      return;
    }
    setReorderItems((current) => {
      const sourceIndex = current.findIndex((email) => email.id === sourceId);
      const targetIndex = current.findIndex((email) => email.id === targetId);
      if (sourceIndex < 0 || targetIndex < 0) return current;
      const next = [...current];
      const [moved] = next.splice(sourceIndex, 1);
      const adjustedTargetIndex = next.findIndex((email) => email.id === targetId);
      const insertIndex = position === "after" ? adjustedTargetIndex + 1 : adjustedTargetIndex;
      next.splice(insertIndex, 0, moved);
      return next;
    });
    setDropTarget(null);
  }

  async function saveRearrangeMode() {
    setSavingReorder(true);
    setError("");
    try {
      const saved = await updateChronologyOrder(
        numericCaseId,
        reorderItems.map((email) => email.id)
      );
      setEmails((current) =>
        current.map((email) => saved.find((savedEmail) => savedEmail.id === email.id) ?? email)
      );
      cancelRearrangeMode();
      await refreshAudit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chronology order could not be saved");
    } finally {
      setSavingReorder(false);
    }
  }

  async function resetChronologyOrder() {
    setSavingReorder(true);
    setError("");
    try {
      const saved = await updateChronologyOrder(numericCaseId, []);
      setEmails((current) =>
        current.map((email) => saved.find((savedEmail) => savedEmail.id === email.id) ?? email)
      );
      cancelRearrangeMode();
      await refreshAudit();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chronology order could not be reset");
    } finally {
      setSavingReorder(false);
    }
  }

  async function onChangeTimezone(tz: string) {
    if (!tz || tz === caseRecord?.default_tz) return;
    await updateCase(numericCaseId, { default_tz: tz });
    await refresh();
  }

  // Importing a bundle always creates a NEW case (full id remap); on success we
  // navigate to it rather than mutating the current case.
  async function onImportBundle(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = ""; // allow re-selecting the same file later
    if (!file) return;
    setError("");
    setImporting(true);
    try {
      const preview = await importCasePreview(file);
      if (!preview.compatible) {
        setError(preview.refuse_reason || "This bundle is not compatible with the current app version.");
        return;
      }
      const summary = `Import "${preview.case_name ?? "case"}" as a new matter — ${preview.counts.emails} emails, ${preview.counts.attachments} attachments?`;
      if (!window.confirm(summary)) return;
      const created = await importCaseBundle(file);
      navigate(`/cases/${created.public_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import case");
    } finally {
      setImporting(false);
    }
  }

  function onJumpToMonth(monthKey: string) {
    if (viewMode !== "chrono") {
      setPendingMonthKey(monthKey);
      setViewMode("chrono");
      return;
    }
    scrollToMonth(monthKey);
  }

  function scrollToMonth(monthKey: string) {
    window.requestAnimationFrame(() => {
      document.getElementById(monthAnchorId(monthKey))?.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
      setActiveMonthKey(monthKey);
    });
  }

  function scrollToEmail(emailId: number) {
    if (viewMode !== "chrono") setViewMode("chrono");
    window.requestAnimationFrame(() => {
      document.getElementById(`email-${emailId}`)?.scrollIntoView({
        behavior: "smooth",
        block: "center"
      });
    });
    setFlashEmailId(emailId);
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => {
      setFlashEmailId(null);
      flashTimer.current = null;
    }, 1600);
  }

  async function exportChronology() {
    const Excel = await import("exceljs");
    const workbook = new Excel.Workbook();
    workbook.creator = "Chronology";
    workbook.created = new Date();

    const sheet = workbook.addWorksheet("Chronology", {
      views: [{ state: "frozen", ySplit: 1 }]
    });
    const columns = [
      { name: "No", width: 8 },
      { name: "Doc ID", width: 12 },
      { name: "Date", width: 22 },
      { name: "Thread", width: 12 },
      { name: "From", width: 30 },
      { name: "To", width: 34 },
      { name: "Cc", width: 28 },
      { name: "Subject", width: 42 },
      { name: "Body", width: 80 },
      { name: "Source", width: 48 },
      { name: "Important", width: 12 },
      { name: "Notes", width: 42 },
      { name: "Confidence", width: 14 },
      { name: "Flags", width: 30 },
      { name: "Message ID", width: 36 },
      { name: "Kind", width: 14 },
      { name: "Tags", width: 28 }
    ];
    const threadLabels = new Map<string, number>();
    const rows = displayEmails.map((email, index) => {
      const key = threadKey(email);
      if (!threadLabels.has(key)) threadLabels.set(key, threadLabels.size + 1);
      return [
        index + 1,
        email.doc_id ?? "",
        formatExportDate(email.date_utc, timeZone),
        `Thread ${threadLabels.get(key)}`,
        email.from_addr,
        email.to.join("; "),
        email.cc.join("; "),
        safeExcelText(email.subject),
        safeExcelText(email.body_text),
        safeExcelText(email.source_file_display),
        email.important ? "Yes" : "No",
        safeExcelText(email.notes),
        email.parse_confidence,
        email.flags.join("; "),
        safeExcelText(email.message_id ?? ""),
        email.source_kind,
        safeExcelText(email.tags.map((tag) => tag.name).join("; "))
      ];
    });

    sheet.addTable({
      name: "ChronologyTable",
      ref: "A1",
      headerRow: true,
      totalsRow: false,
      style: {
        theme: "TableStyleMedium2",
        showRowStripes: false
      },
      columns: columns.map((column) => ({ name: column.name, filterButton: true })),
      rows
    });
    sheet.columns = columns.map((column) => ({ width: column.width }));
    styleChronologySheet(sheet, displayEmails);

    const buffer = await workbook.xlsx.writeBuffer();
    const blob = new Blob([buffer], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${safeExportName(caseRecord?.name ?? "chronology")}-chronology.xlsx`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  const timeZone = caseRecord?.default_tz;
  const filtersActive = Boolean(query.trim()) || tagFilterId !== null;
  const allChronologyEmailsLoaded = !hasMoreEmails && displayEmails.length === emailTotal;
  const canRearrange =
    viewMode === "chrono" &&
    !filtersActive &&
    !loading &&
    allChronologyEmailsLoaded &&
    displayEmails.length > 1;
  const mapReady = Boolean(ingestMapStatus?.ready);
  const mapButtonTitle = job?.status === "running"
    ? "Map is available after ingest finishes"
    : ingestMapStatusLoading
      ? "Checking map readiness"
      : mapReady
        ? "Review where parsed source text went"
        : ingestMapStatus?.source_count === 0
          ? "Map is available after emails are added"
          : "Map is being prepared";

  return (
    <section className="case-page">
      <header className="case-header">
        <Link className="back-link" to="/">
          <ArrowLeft size={17} /> Cases
        </Link>
        <div>
          <p className="eyebrow">Chronology</p>
          <h1>{caseRecord?.name ?? "Case"}</h1>
        </div>
        <div className="header-actions">
          <div className="action-group">
            <button
              className="header-action-btn"
              type="button"
              disabled={rearrangeMode}
              onClick={() => void exportChronology()}
              title="Export chronology to Excel"
              aria-label="Export chronology to Excel"
            >
              <Download size={15} /> <span>Excel</span>
            </button>
            <button
              className="header-action-btn"
              type="button"
              disabled={rearrangeMode}
              onClick={() => void exportCaseBundle(numericCaseId ?? 0, caseRecord?.name)}
              title="Export full case archive (.ecz) for backup or import"
              aria-label="Export case bundle"
            >
              <Download size={15} /> <span>Bundle</span>
            </button>
            <button
              className="header-action-btn"
              type="button"
              disabled={importing}
              onClick={() => importInputRef.current?.click()}
              title="Import a case from an exported .ecz bundle (creates a new matter)"
              aria-label="Import case bundle"
            >
              <Upload size={15} /> <span>{importing ? "Importing…" : "Import"}</span>
            </button>
            <input
              ref={importInputRef}
              type="file"
              accept=".ecz,application/zip"
              style={{ display: "none" }}
              onChange={onImportBundle}
            />
          </div>
          <span className="header-sep" aria-hidden="true" />
          <TimezoneSelect value={timeZone} onChange={(tz) => void onChangeTimezone(tz)} />
          <ThemeToggle />
          <button className="icon-button" title="Refresh" type="button" onClick={() => void refresh()}>
            <RefreshCw size={18} />
          </button>
        </div>
      </header>

      <div
        className={`case-layout ${sidebarCollapsed ? "collapsed" : ""}`}
        style={{ "--sidebar-w": `${sidebarWidth}px` } as CSSProperties}
      >
        <aside className="case-sidebar">
          {!sidebarCollapsed && (
            <div
              className="sidebar-resizer"
              role="separator"
              aria-orientation="vertical"
              title="Drag to resize panel"
              onPointerDown={startSidebarResize}
              onPointerMove={onSidebarResizeMove}
              onPointerUp={endSidebarResize}
            />
          )}
          <div className="case-sidebar-scroll">
          {sidebarCollapsed ? (
            <nav className="sidebar-rail" aria-label="Workspace">
              <button
                className="rail-btn"
                type="button"
                title="Expand panel"
                aria-label="Expand panel"
                onClick={() => setSidebarCollapsedPersisted(false)}
              >
                <ChevronRight size={18} />
              </button>
              <button
                className="rail-btn"
                type="button"
                title="Tags"
                aria-label="Tags"
                onClick={() => {
                  setSidebarCollapsedPersisted(false);
                  setTagManagerOpen(true);
                }}
              >
                <Tags size={18} />
                {tags.length > 0 && <span className="rail-badge">{tags.length}</span>}
              </button>
              <button
                className="rail-btn"
                type="button"
                title="Email trash"
                aria-label="Email trash"
                onClick={() => {
                  setSidebarCollapsedPersisted(false);
                  setEmailTrashOpen(true);
                }}
              >
                <Trash2 size={18} />
                {emailTrash.length > 0 && <span className="rail-badge">{emailTrash.length}</span>}
              </button>
              <button
                className="rail-btn"
                type="button"
                title="Review duplicates"
                aria-label="Review duplicates"
                onClick={() => void openClusterReview()}
              >
                <Copy size={18} />
              </button>
              <button
                className="rail-btn"
                type="button"
                title="Audit trail"
                aria-label="Audit trail"
                onClick={() => {
                  setSidebarCollapsedPersisted(false);
                  setAuditOpen(true);
                }}
              >
                <History size={18} />
              </button>
              {job && (
                <button
                  className="rail-btn"
                  type="button"
                  title="Last ingest"
                  aria-label="Last ingest"
                  onClick={() => {
                    setSidebarCollapsedPersisted(false);
                    setJobPanelOpen(true);
                  }}
                >
                  <Inbox size={18} />
                </button>
              )}
            </nav>
          ) : (
          <>
          <div className="sidebar-head">
            <Link className="sidebar-title" to="/" title="Back to all matters">
              Workspace
            </Link>
            <button
              className="collapse-btn"
              type="button"
              title="Minimise panel"
              aria-label="Minimise panel"
              onClick={() => setSidebarCollapsedPersisted(true)}
            >
              <ChevronLeft size={16} />
            </button>
          </div>
          <UploadDropzone
            onUpload={onUpload}
            onFolderImport={onFolderImport}
            availableTags={tags}
            activeJob={job}
            defaultContainsCjk={caseRecord?.has_cjk_content ?? false}
          />
          <button
            className={`audit-toggle ${tagManagerOpen ? "active" : ""}`}
            type="button"
            onClick={() => setTagManagerOpen((value) => !value)}
          >
            <Tags size={16} />
            <span>Tags</span>
            <strong>{tags.length}</strong>
          </button>
          {tagManagerOpen && (
            <TagManager
              tags={tags}
              onCreate={async (name, color) => {
                await onCreateTag(name, color);
              }}
              onUpdate={onUpdateTag}
              onDelete={onDeleteTag}
            />
          )}
          <button
            className={`trash-toggle ${emailTrashOpen ? "active" : ""}`}
            type="button"
            onClick={() => setEmailTrashOpen((value) => !value)}
          >
            <Trash2 size={16} />
            <span>Email trash</span>
            <strong>{emailTrash.length}</strong>
          </button>
          {emailTrashOpen && (
            <EmailTrashPanel trash={emailTrash} onRestore={(emailId) => void onRestoreEmail(emailId)} />
          )}
          <button
            className={`audit-toggle ${clusterReviewOpen ? "active" : ""}`}
            type="button"
            onClick={() => void openClusterReview()}
          >
            <Copy size={16} />
            <span>Review duplicates</span>
          </button>
          <TimelineNavigator
            activeKey={activeMonthKey}
            buckets={monthGroups}
            onJump={onJumpToMonth}
            total={emails.length}
          />
          <button
            className={`audit-toggle ${auditOpen ? "active" : ""}`}
            type="button"
            onClick={() => setAuditOpen((value) => !value)}
          >
            <History size={16} />
            <span>Audit trail</span>
            <strong>{auditEvents.length}</strong>
          </button>
          {auditOpen && <AuditTrailPanel events={auditEvents} onJumpToEmail={scrollToEmail} />}
          {folders.length > 0 && (
            <div className="folder-panel">
              <h2>Tracked folders</h2>
              <p className="folder-panel-hint">Re-scan a folder to ingest only newly added files.</p>
              {folders.map((folder) => (
                <div className="tracked-folder" key={folder.id}>
                  <div className="tracked-folder-info">
                    <span className="tracked-folder-path" title={folder.folder_path}>
                      {folder.folder_path}
                    </span>
                    <small>
                      {folder.recursive ? "Recursive" : "Top level"}
                      {folder.last_scanned_at
                        ? ` · last scanned ${formatExportDate(folder.last_scanned_at, timeZone)}`
                        : ""}
                    </small>
                  </div>
                  <button
                    type="button"
                    className="chain-button"
                    disabled={refreshingFolderId !== null || job?.status === "running"}
                    onClick={() => void onRefreshFolder(folder.id)}
                    title="Re-scan this folder for new files"
                  >
                    <RefreshCw size={14} />
                    {refreshingFolderId === folder.id ? "Refreshing..." : "Refresh"}
                  </button>
                </div>
              ))}
            </div>
          )}
          {job && (
            <>
              <button
                className={`audit-toggle ${jobPanelOpen ? "active" : ""}`}
                type="button"
                onClick={() => setJobPanelOpen((value) => !value)}
              >
                <Inbox size={16} />
                <span>{job.status === "running" ? "Ingest progress" : "Last ingest"}</span>
                <strong>
                  {job.processed_files}/{job.total_files}
                </strong>
              </button>
              {jobPanelOpen && (
                <div className="job-panel">
                  <p>
                    {job.processed_files} of {job.total_files} parsed, {job.failed_files} failed
                  </p>
                  <div className="job-progress" aria-hidden="true">
                    <span style={{ width: `${ingestProgressPercent(job)}%` }} />
                  </div>
                  {job.files.map((file) => (
                    <div className={`job-file ${file.status}`} key={file.id}>
                      <span>{file.source_file_display}</span>
                      <small>{file.error ?? file.status}</small>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
          </>
          )}
          </div>
        </aside>

        <div className="timeline-panel">
          <div className="filter-bar" ref={toolbarRef}>
            <div
              className={`view-toggle ${toolbarIconsOnly ? "icons-only" : ""}`}
              role="tablist"
              aria-label="View mode"
            >
              <button
                type="button"
                disabled={rearrangeMode}
                onClick={() => setManualDrawerOpen(true)}
                title="Add manual email"
                aria-label="Add manual email"
              >
                <Plus size={14} /> <span className="lbl">Add</span>
              </button>
              <button
                type="button"
                disabled={rearrangeMode || !mapReady}
                onClick={() => void openCaseIngestMap()}
                title={mapButtonTitle}
                aria-label="Open ingest map"
              >
                <FileSearch size={14} /> <span className="lbl">Map</span>
              </button>
              <button
                className={rearrangeMode ? "active" : ""}
                type="button"
                disabled={!canRearrange && !rearrangeMode}
                onClick={startRearrangeMode}
                title={
                  filtersActive
                    ? "Clear filters before rearranging"
                    : !allChronologyEmailsLoaded
                      ? "Apply with no filters before rearranging all emails"
                    : "Drag all chronology emails into a manual order"
                }
              >
                <ArrowUpDown size={14} /> <span className="lbl">Rearrange</span>
              </button>
              <button
                className={viewMode === "chrono" ? "active" : ""}
                type="button"
                disabled={rearrangeMode}
                onClick={() => setViewMode("chrono")}
                title="Chronology"
                aria-label="Chronology"
              >
                <Clock size={14} /> <span className="lbl">Chronology</span>
              </button>
            </div>
            <UnifiedFilterBox
              text={searchDraft}
              selectedTagId={tagFilterId}
              tags={tags}
              disabled={rearrangeMode}
              onTextChange={setSearchDraft}
              onTagChange={setTagFilterId}
              onApply={() => void submitSearch()}
              onClear={() => void clearFilters()}
            />
          </div>

          {rearrangeMode && (
            <div className="reorder-toolbar">
              <div>
                <strong>Rearrange chronology</strong>
                <span>Cancel returns to the last saved order. Original chrono clears the manual order.</span>
              </div>
              <div>
                <button
                  className="ghost-button"
                  type="button"
                  disabled={savingReorder}
                  title="Clear saved manual order and sort by email dates"
                  onClick={() => void resetChronologyOrder()}
                >
                  <RotateCcw size={15} /> Original chrono
                </button>
                <button
                  className="ghost-button"
                  type="button"
                  disabled={savingReorder}
                  onClick={cancelRearrangeMode}
                >
                  <X size={15} /> Cancel
                </button>
                <button
                  className="save-button"
                  type="button"
                  disabled={savingReorder}
                  onClick={() => void saveRearrangeMode()}
                >
                  <Save size={15} /> {savingReorder ? "Saving..." : "Save order"}
                </button>
              </div>
            </div>
          )}

          {error && <div className="notice error">{error}</div>}
          {loading && <div className="notice">Loading {viewMode}...</div>}
          {!loading && emails.length === 0 && (
            <div className="empty-state">
              <h2>No emails yet</h2>
              <p>Upload `.eml`, `.msg`, `.pdf`, or `.docx` files, or add an email manually.</p>
            </div>
          )}
          {viewMode === "chrono" && rearrangeMode ? (
            <ChronologyReorderList
              draggedId={draggedReorderId}
              dropTarget={dropTarget}
              items={reorderItems}
              onDragEnd={() => {
                setDraggedReorderId(null);
                setDropTarget(null);
              }}
              onDragStart={(emailId) => {
                setDraggedReorderId(emailId);
                setDropTarget(null);
              }}
              onDropTargetChange={setDropTarget}
              onMove={moveReorderEmail}
              timeZone={timeZone}
            />
          ) : viewMode === "chrono" ? (
            <div className="timeline-list">
              {monthGroups.map((group) => (
                <Fragment key={group.key}>
                  <section
                    className="month-marker"
                    data-month-key={group.key}
                    id={monthAnchorId(group.key)}
                  >
                    <h2>{group.label}</h2>
                    <span>
                      {group.count} {group.count === 1 ? "email" : "emails"}
                    </span>
                  </section>
                  {group.emails.map((email) => (
                    <EmailCard
                      email={email}
                      key={email.id}
                      selected={selected?.id === email.id}
                      onSelect={() => setSelected(email)}
                      onOpenChain={() =>
                        setChainPanelEmail((current) => (current?.id === email.id ? null : email))
                      }
                      onOpenDuplicates={() => void openDuplicateReview(email)}
                      onOpenSnip={() => setSnipEmailRecord(email)}
                      onOpenIngestMap={() => void openEmailIngestMap(email.id)}
                      mapReady={mapReady}
                      mapTitle={mapButtonTitle}
                      onOpenSource={() => void onOpenSource(email.id)}
                      onDelete={() => onDeleteEmail(email.id)}
                      onSaveNotes={(notes) => onSaveEmailAnnotation(email.id, { notes })}
                      onToggleImportant={() =>
                        onSaveEmailAnnotation(email.id, { important: !email.important })
                      }
                      relationState={relationStates.get(email.id) ?? null}
                      timeZone={timeZone}
                      availableTags={tags}
                      onAddTag={(tagId) => onAddTagToEmail(email.id, tagId)}
                      onRemoveTag={(tagId) => onRemoveTagFromEmail(email.id, tagId)}
                      onCreateTag={(name) => onCreateTagForEmail(email.id, name)}
                      flash={flashEmailId === email.id}
                    />
                  ))}
                </Fragment>
              ))}
              {hasMoreEmails && (
                <button
                  className="load-more-button"
                  type="button"
                  disabled={loadingMore}
                  onClick={() => void loadMoreEmails()}
                >
                  {loadingMore ? "Loading..." : `Load more (${displayEmails.length}/${emailTotal})`}
                </button>
              )}
            </div>
          ) : (
            <div className="thread-list">
              {threadGroups.map((group) => (
                <section className="thread-group" key={group.threadId}>
                  <header>
                    <div>
                      <span>{group.emails.length} messages</span>
                      <h2>{group.subject}</h2>
                    </div>
                    <small>{group.range}</small>
                  </header>
                  <div className="timeline-list">
                    {group.emails.map((email) => (
                      <EmailCard
                        email={email}
                        key={email.id}
                        selected={selected?.id === email.id}
                        onSelect={() => setSelected(email)}
                        onOpenChain={() =>
                          setChainPanelEmail((current) => (current?.id === email.id ? null : email))
                        }
                        onOpenDuplicates={() => void openDuplicateReview(email)}
                        onOpenSnip={() => setSnipEmailRecord(email)}
                        onOpenIngestMap={() => void openEmailIngestMap(email.id)}
                        mapReady={mapReady}
                        mapTitle={mapButtonTitle}
                        onOpenSource={() => void onOpenSource(email.id)}
                        onDelete={() => onDeleteEmail(email.id)}
                        onSaveNotes={(notes) => onSaveEmailAnnotation(email.id, { notes })}
                        onToggleImportant={() =>
                          onSaveEmailAnnotation(email.id, { important: !email.important })
                        }
                        relationState={relationStates.get(email.id) ?? null}
                        timeZone={timeZone}
                        availableTags={tags}
                        onAddTag={(tagId) => onAddTagToEmail(email.id, tagId)}
                        onRemoveTag={(tagId) => onRemoveTagFromEmail(email.id, tagId)}
                        onCreateTag={(name) => onCreateTagForEmail(email.id, name)}
                        flash={flashEmailId === email.id}
                      />
                    ))}
                  </div>
                </section>
              ))}
              {hasMoreEmails && (
                <button
                  className="load-more-button"
                  type="button"
                  disabled={loadingMore}
                  onClick={() => void loadMoreEmails()}
                >
                  {loadingMore ? "Loading..." : `Load more (${emails.length}/${emailTotal})`}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <ManualEmailDrawer
        open={manualDrawerOpen}
        onClose={() => setManualDrawerOpen(false)}
        onCreate={onCreateManualEmail}
      />
      <EmailSnipDialog
        email={snipEmailRecord}
        saving={snipSaving}
        onPreview={(emailId, splitOffsets) => previewSnipEmail(emailId, { split_offsets: splitOffsets })}
        onClose={() => {
          if (!snipSaving) setSnipEmailRecord(null);
        }}
        onApply={(splitOffsets, parts) =>
          snipEmailRecord ? onApplySnip(snipEmailRecord.id, splitOffsets, parts) : Promise.resolve()
        }
      />
      {ingestMapOpen && (
        <IngestMapDialog
          summary={ingestMapSummary}
          detail={ingestMapDetail}
          selectedSourceId={ingestMapEmailId}
          loading={ingestMapLoading}
          detailLoading={ingestMapDetailLoading}
          error={ingestMapError}
          caseName={caseRecord?.name ?? "chronology"}
          onClose={() => setIngestMapOpen(false)}
          onSelectSource={(emailId) => void loadIngestMapDetail(emailId)}
          onLoadDetail={getEmailIngestMap}
          onCreateCard={onCreateCardFromMap}
          onCreateGroup={onCreateGroupedCardFromMap}
          onJumpToEmail={(emailId) => {
            scrollToEmail(emailId);
            setIngestMapOpen(false);
          }}
        />
      )}
      <EmailDrawer
        email={selected}
        onClose={() => setSelected(null)}
        onSave={onSave}
        timeZone={caseRecord?.default_tz}
      />
      <DuplicateReviewDialog
        activeEmail={duplicateReviewEmail}
        candidates={duplicateCandidates}
        loading={duplicateLoading}
        savingId={duplicateSavingId}
        onClose={() => {
          setDuplicateReviewEmail(null);
          setDuplicateCandidates([]);
        }}
        onMark={(candidate, duplicateEmailId) =>
          void decideDuplicateCandidate(candidate, "duplicate", duplicateEmailId)
        }
        onDissimilar={(candidate) => void decideDuplicateCandidate(candidate, "dissimilar")}
        timeZone={timeZone}
      />
      <DuplicateClusterDialog
        open={clusterReviewOpen}
        clusters={duplicateClusters}
        loading={clusterLoading}
        exactCount={exactDuplicateCount}
        busy={clusterBusy}
        onClose={() => setClusterReviewOpen(false)}
        onResolveCluster={(cluster, canonicalId) => void onResolveCluster(cluster, canonicalId)}
        onResolveExact={() => void onResolveExactDuplicates()}
        timeZone={timeZone}
      />
      <ChainOrderPanel
        activeEmail={chainPanelEmail}
        emails={chainPanelEmails}
        onClose={() => setChainPanelEmail(null)}
        onSave={onSaveChainOrder}
        onScrollToEmail={scrollToEmail}
        timeZone={timeZone}
      />
    </section>
  );
}

function ChronologyReorderList({
  draggedId,
  dropTarget,
  items,
  onDragEnd,
  onDragStart,
  onDropTargetChange,
  onMove,
  timeZone
}: {
  draggedId: number | null;
  dropTarget: { id: number; position: DropPosition } | null;
  items: EmailRecord[];
  onDragEnd: () => void;
  onDragStart: (emailId: number) => void;
  onDropTargetChange: (target: { id: number; position: DropPosition } | null) => void;
  onMove: (sourceId: number, targetId: number, position: DropPosition) => void;
  timeZone?: string;
}) {
  return (
    <div className="chrono-order-list">
      {items.map((email, index) => (
        <article
          className={[
            "chrono-order-card",
            draggedId === email.id ? "dragging" : "",
            dropTarget?.id === email.id ? `drop-${dropTarget.position}` : ""
          ]
            .filter(Boolean)
            .join(" ")}
          draggable
          key={email.id}
          onDragStart={(event) => {
            onDragStart(email.id);
            event.dataTransfer.effectAllowed = "move";
          }}
          onDragEnd={onDragEnd}
          onDragLeave={(event) => {
            const nextTarget = event.relatedTarget;
            if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
            if (dropTarget?.id === email.id) onDropTargetChange(null);
          }}
          onDragOver={(event) => {
            event.preventDefault();
            if (draggedId === null || draggedId === email.id) {
              onDropTargetChange(null);
              return;
            }
            const position = dropPositionForEvent(event);
            onDropTargetChange({ id: email.id, position });
          }}
          onDrop={(event) => {
            event.preventDefault();
            const position = dropTarget?.id === email.id ? dropTarget.position : dropPositionForEvent(event);
            if (draggedId !== null) onMove(draggedId, email.id, position);
          }}
        >
          <button
            className="drag-handle"
            type="button"
            title="Drag to reorder"
            draggable
            onDragStart={(event) => {
              onDragStart(email.id);
              event.dataTransfer.effectAllowed = "move";
            }}
          >
            <GripVertical size={17} />
          </button>
          <div className="chrono-order-index">{index + 1}</div>
          <div className="chrono-order-date">
            <strong>{formatReorderDay(email.date_utc, timeZone)}</strong>
            <span>{formatReorderTime(email.date_utc, timeZone)}</span>
          </div>
          <div className="chrono-order-main">
            <div className="chrono-order-meta">
              <strong>{email.from_addr || "Unknown sender"}</strong>
              <span>{formatRecipients(email.to)}</span>
            </div>
            <h2>{email.subject}</h2>
            <p>{compactSnippet(email.body_text)}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

function formatReorderDay(value?: string | null, timeZone?: string) {
  const date = validDate(value);
  if (!date) return value ? "Invalid date" : "No date";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone }).format(date);
}

function dropPositionForEvent(event: DragEvent<HTMLElement>): DropPosition {
  const rect = event.currentTarget.getBoundingClientRect();
  return event.clientY > rect.top + rect.height / 2 ? "after" : "before";
}

function formatReorderTime(value?: string | null, timeZone?: string) {
  const date = validDate(value);
  if (!date) return "--:--";
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZone }).format(date);
}

function formatRecipients(values: string[]) {
  if (!values.length) return "No recipients";
  return values.join(", ");
}

function compactSnippet(value: string) {
  const text = value.replace(/\s+/g, " ").trim();
  if (!text) return "No plain-text body captured.";
  return text.length > 160 ? `${text.slice(0, 160).trimEnd()}...` : text;
}

function ingestProgressPercent(job: IngestJob) {
  if (!job.total_files) return 0;
  return Math.min(100, Math.max(0, Math.round((job.processed_files / job.total_files) * 100)));
}

function mergeEmails(current: EmailRecord[], incoming: EmailRecord[]) {
  const byId = new Map(current.map((email) => [email.id, email]));
  incoming.forEach((email) => byId.set(email.id, email));
  return Array.from(byId.values());
}

function groupEmailMonths(emails: EmailRecord[], timeZone?: string): EmailMonthGroup[] {
  const groups: EmailMonthGroup[] = [];
  const byKey = new Map<string, EmailMonthGroup>();
  const noDateEmails: EmailRecord[] = [];

  emails.forEach((email) => {
    const bucket = monthBucket(email.date_utc, timeZone);
    if (!bucket) {
      noDateEmails.push(email);
      return;
    }
    let group = byKey.get(bucket.key);
    if (!group) {
      group = { ...bucket, count: 0, emails: [] };
      byKey.set(bucket.key, group);
      groups.push(group);
    }
    group.count += 1;
    group.emails.push(email);
  });

  if (noDateEmails.length) {
    groups.push({
      key: "no-date",
      label: "No date",
      count: noDateEmails.length,
      emails: noDateEmails
    });
  }

  return groups;
}

function monthBucket(value?: string | null, timeZone?: string) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "2-digit",
    timeZone
  }).formatToParts(date);
  const year = parts.find((part) => part.type === "year")?.value;
  const month = parts.find((part) => part.type === "month")?.value;
  if (!year || !month) return null;
  return {
    key: `${year}-${month}`,
    label: new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric", timeZone }).format(
      date
    )
  };
}

function monthAnchorId(monthKey: string) {
  return `month-${monthKey}`;
}

function groupThreads(emails: EmailRecord[], timeZone?: string) {
  const groups = new Map<string, EmailRecord[]>();
  emails.forEach((email) => {
    const key = email.thread_id ?? `email:${email.id}`;
    groups.set(key, [...(groups.get(key) ?? []), email]);
  });
  return Array.from(groups.entries()).map(([threadId, groupEmails]) => {
    const sorted = [...groupEmails].sort(compareForChainDisplay);
    return {
      threadId,
      emails: sorted,
      subject: stripSubjectPrefix(sorted[0]?.subject ?? "(no subject)"),
      range: formatThreadRange(sorted, timeZone)
    };
  });
}

function compareForDisplay(a: EmailRecord, b: EmailRecord) {
  const aChrono = a.manual_chrono_order;
  const bChrono = b.manual_chrono_order;
  if (aChrono !== null && aChrono !== undefined) {
    if (bChrono === null || bChrono === undefined) return -1;
    return aChrono - bChrono || compareForChainDisplay(a, b);
  }
  if (bChrono !== null && bChrono !== undefined) return 1;

  return compareForChainDisplay(a, b);
}

function stripSubjectPrefix(value: string) {
  return value.replace(/^(\s*(re|fw|fwd):\s*)+/i, "").trim() || "(no subject)";
}

function formatThreadRange(emails: EmailRecord[], timeZone?: string) {
  const dates = emails
    .map((email) => email.date_utc)
    .map((value) => validDate(value))
    .filter((date): date is Date => Boolean(date));
  if (!dates.length) return "No dates";
  const first = dates[0];
  const last = dates[dates.length - 1];
  const formatter = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone });
  if (first.toDateString() === last.toDateString()) return formatter.format(first);
  return `${formatter.format(first)} - ${formatter.format(last)}`;
}

function formatExportDate(value?: string | null, timeZone?: string) {
  const date = validDate(value);
  if (!date) return value ? "Invalid date" : "";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone
  }).format(date);
}

function validDate(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function safeExportName(value: string) {
  return (value || "chronology").replace(/[\\/:*?"<>|]+/g, "-").trim() || "chronology";
}

function safeExcelText(value: string) {
  return /^[=+\-@]/.test(value) ? `'${value}` : value;
}

function styleChronologySheet(sheet: ExcelJS.Worksheet, emails: EmailRecord[]) {
  const threadColors = [
    "EAF2F8",
    "EAF7EA",
    "FFF4DB",
    "F7EAF8",
    "E9F7F7",
    "FCEEEE",
    "EEF0FF",
    "F4F4F5"
  ];
  const threadColorByKey = new Map<string, string>();
  emails.forEach((email) => {
    const key = threadKey(email);
    if (!threadColorByKey.has(key)) {
      threadColorByKey.set(key, threadColors[threadColorByKey.size % threadColors.length]);
    }
  });

  const header = sheet.getRow(1);
  header.height = 24;
  header.eachCell((cell) => {
    cell.font = { bold: true, color: { argb: "FFFFFFFF" } };
    cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF1F2937" } };
    cell.alignment = { vertical: "middle", wrapText: true };
    cell.border = thinBorder("FF111827");
  });

  emails.forEach((email, index) => {
    const row = sheet.getRow(index + 2);
    const color = threadColorByKey.get(threadKey(email)) || "FFFFFF";
    row.height = Math.min(96, Math.max(24, Math.ceil((email.body_text.length || 1) / 120) * 18));
    row.eachCell((cell) => {
      cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: `FF${color}` } };
      cell.alignment = { vertical: "top", wrapText: true };
      cell.border = thinBorder("FFE5E7EB");
    });
    if (email.important) {
      row.getCell(11).font = { bold: true, color: { argb: "FFB45309" } };
    }
    if (email.notes) {
      row.getCell(12).font = { italic: true, color: { argb: "FF374151" } };
    }
  });
  // NB: do not set sheet.autoFilter here — the chronology table (addTable with
  // filterButton columns) already owns an autoFilter over this range. A second,
  // worksheet-level autoFilter over the same cells makes Excel treat the file as
  // corrupt and silently discard the table part on open.
}

function thinBorder(color: string): Partial<ExcelJS.Borders> {
  return {
    top: { style: "thin", color: { argb: color } },
    left: { style: "thin", color: { argb: color } },
    bottom: { style: "thin", color: { argb: color } },
    right: { style: "thin", color: { argb: color } }
  };
}

const TIME_ZONES: string[] =
  typeof (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf ===
  "function"
    ? (Intl as unknown as { supportedValuesOf: (key: string) => string[] }).supportedValuesOf("timeZone")
    : ["UTC", "America/New_York", "America/Los_Angeles", "Europe/London", "Asia/Singapore", "Asia/Shanghai"];

const PINNED_ZONE = "Asia/Singapore";

function TimezoneSelect({ value, onChange }: { value?: string; onChange: (tz: string) => void }) {
  const current = value || "UTC";
  // Singapore time pinned to the top, then the active matter zone, then the rest.
  const rest = TIME_ZONES.filter((zone) => zone !== PINNED_ZONE && zone !== current);
  const options = [PINNED_ZONE, ...(current !== PINNED_ZONE ? [current] : []), ...rest];
  return (
    <label className="tz-select" title="Matter timezone (used to interpret dates without a zone)">
      <Globe size={15} />
      <select value={current} onChange={(event) => onChange(event.target.value)}>
        {options.map((zone) => (
          <option key={zone} value={zone}>
            {zone}
          </option>
        ))}
      </select>
    </label>
  );
}
