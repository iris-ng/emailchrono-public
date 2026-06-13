# Email Chronology Builder

Local web app for building an email chronology from `.eml` and `.msg` files. It parses standalone emails plus quoted/trailing and attached emails, stores extracted metadata and attachments locally, and lets the user review, edit, thread, reorder, split (snip), tag, audit, and screen emails for suspected duplicates.

## Current Features

- Import `.eml`, `.msg`, `.pdf`, and `.docx` files by upload or local folder path, with live per-file ingest progress. PDFs and Word documents containing printed/exported emails are parsed for headers and content; non-email documents are skipped gracefully.
- Extract standalone emails plus quoted/trailing messages where reply-chain structure can be detected; email-bearing attachments (forwarded `.eml`/`.msg`, `message/rfc822`, embedded `.msg`) are expanded into first-class timeline rows.
- Build chronology and thread views with editable email metadata and a permanent notes panel; long lists load progressively (paged) with a Load more control.
- Render emails as plain text or sanitized HTML, under a per-matter default timezone.
- Search subject and body text with SQLite FTS.
- Manually rearrange the global chronology order or per-thread chain order.
- Split (snip) an incorrectly combined email card into multiple cards via a preview/approve workflow.
- Tag emails: case-scoped tags applied at upload, per-email, or in bulk, with tag filters and tag columns in the Excel export.
- Move emails to trash and restore them for 30 days.
- Keep an append-only, hash-linked audit trail for major case/email changes (including upload sessions).
- Flag suspected duplicate emails for user review without deleting source records.
- Export the chronology to a styled `.xlsx` workbook with safe Excel formula escaping to prevent injection attacks.
- Import/export complete cases as `.ecz` bundles (zip format with manifest, emails, source blobs, and attachments). Source blobs are content-addressed and validated on import to prevent path-traversal attacks.

## Duplicate Review

The app stores suspected duplicate pairs in `email_duplicate_candidates`. Pending candidates appear on email cards as a `Duplicates N` badge.

Duplicate detection uses several signals:

- exact uploaded source SHA-256 match;
- normalized `Message-ID` match;
- normalized body hash match;
- MinHash-estimated body overlap (Jaccard similarity) — catches near-duplicates that differ by added footers, reordered paragraphs, or light edits;
- body containment — identifies forwarded or quoted emails where one body is embedded in another;
- high normalized body character similarity (SequenceMatcher), with subject/sender/date context when needed.

MinHash signatures and LSH band keys are persisted per email and lazily backfilled at ingest completion; pair scoring reuses precomputed fingerprints to avoid per-pair re-normalization.

Clicking the badge opens a review popup. The user can mark either email as the duplicate, or mark the pair as dissimilar. Decisions are retained and audit logged; marking a duplicate does not delete or trash the email.

## Tagging

Tags are case-scoped (label + color) and linked to emails through a many-to-many `email_tags` table. Tags can be applied to every top-level email created by an upload/import, edited per-email from the chronology, or applied in bulk to a multi-selection. The toolbar offers a tag filter, and tag names are included in the Excel export and in audit events.

## Splitting (Snip)

When parsing combines several emails into one card, the **Snip** action splits it. The user draws split lines over the body and gets a preview of the proposed cards, each editable (from/to/cc/date/subject/body/notes/important) and individually or bulk approvable before ingest. Snip cards use `source_kind='snipped'`; the original is superseded (hidden from the chronology but kept for provenance and audit).

Dates are handled gracefully: a card whose date is blank or cannot be parsed is still created (without a resolved date) and tagged **`Undated`** so it stays in the chronology and is easy to find and fix later — the snip never fails just because one date is unreadable.

## Run

From the repo root in PowerShell:

```powershell
.\scripts\launch.ps1
```

The app runs at:

```text
http://127.0.0.1:8765
```

## Setup From Fresh Checkout

**Install backend dependencies:**

```powershell
python -m pip install -r backend\requirements.txt
```

If pip fails with `SSL: CERTIFICATE_VERIFY_FAILED`, add trusted hosts:

```powershell
python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r backend\requirements.txt
```

**Note on interpreters:** If bare `python` resolves to a system interpreter without the required packages, use the project virtual environment explicitly:

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

**Install frontend dependencies:**

```powershell
cd frontend
npm install
```

`node_modules/` is **not** committed, so this step is required — `npm install` fetches all runtime and dev dependencies (React, Vite, `typescript`, etc.) from `package-lock.json`.

**Build the frontend bundle:**

```powershell
npm run build
```

This compiles TypeScript (`tsc`) and bundles the React app with Vite into `frontend/dist/`, which the backend serves in production.

**Start the app:**

Return to the repo root and run:

```powershell
.\scripts\launch.ps1
```

The app opens at `http://127.0.0.1:8765`.

## Core Files

These are the files/directories that actually run or build the program and are intentionally kept by `.gitignore`:

- `backend/app/**/*.py` - FastAPI application organized in layers:
  - `api/` — HTTP routers: `cases.py`, `ingest.py` (with upload size validation), `emails.py`, `attachments.py`, `tags.py`, `transfer.py` (export/import)
  - `services/` — domain logic: `ingest.py` (core pipeline with size limits), `quotes.py` (quoted-block extraction), `snip.py` (manual split), `duplicates.py` (duplicate scoring), `fingerprint.py` (MinHash/LSH near-duplicate fingerprints), `text_norm.py` (shared text normalization), `dates.py` (timezone normalization), `audit.py` (append-only trail), `tags.py`, `boilerplate.py`, `sanitize.py` (HTML/formula escaping), `nested_email.py`, `email_serialize.py`, `source_store.py` (SHA-256 content-addressing with path validation), `transfer.py` (bundle export/import with blob validation)
  - `repos/` — data access layer over SQLite: `cases.py`, `emails.py`, `duplicates.py`, `threads.py`, `ordering.py`, `ingest_jobs.py`, `case_folders.py`, `dates.py`, `tags.py`, `attachments.py`
  - `parsers/` — email parsing: `eml.py` (RFC 5822), `msg.py` (Outlook `.msg`), `pdf.py` (pdfplumber, with page limit), `docx.py` (python-docx)
  - `models/schemas.py` — Pydantic request/response models
  - `db.py` — SQLite connection, migrations, shared query helpers
  - `config.py` — paths, constants, and resource limits (MAX_INGEST_FILE_BYTES, MAX_INGEST_BATCH_BYTES, MAX_ATTACHMENT_BYTES, MAX_PDF_PAGES)
  - `main.py` — FastAPI app setup with host allowlist and unsafe-method header validation
  - `__main__.py` — entry point (opens browser, runs uvicorn)
- `backend/migrations/*.sql` - SQLite schema migrations, applied in filename order at startup via `db.init_db()`. Forward-only, never edited once applied.
- `backend/requirements.txt` - Python runtime dependencies (FastAPI, uvicorn, sqlite3, bleach, charset-normalizer, extract-msg, tzdata, pydantic).
- `frontend/src/**/*` - React/TypeScript source: `pages/`, `components/`, `api/client.ts`, `types.ts`.
- `frontend/index.html` - Vite HTML entry point.
- `frontend/package.json` and `frontend/package-lock.json` - frontend dependencies (React, Vite, TypeScript, exceljs, lucide-react) and build scripts.
- `frontend/tsconfig.json` and `frontend/vite.config.ts` - TypeScript and Vite configuration.
- `scripts/*.ps1` - PowerShell launch/dev/build helper scripts.
- `README.md`, `CLAUDE.md`, `.gitignore` - repo documentation and conventions.

Everything else is treated as local-only working material or generated output and is ignored, including:

- `data/` - SQLite database and extracted attachments.
- `frontend/node_modules/` - installed frontend dependencies.
- `frontend/dist/` - generated frontend build output.
- `backend/.pytest_cache/`, `__pycache__/`, `*.pyc` - Python caches.
- `test emails/` - local sample/source documents.
- `approach1/`, `.claude/`, `PLAN.MD`, `PROGRESS.MD` - notes, legacy experiments, and local workspace material.
- `backend/tests/` - development tests, not required to run the app.

## Architecture Deep Dive

For detailed architecture, data flow, key design decisions, and code conventions, see **`CLAUDE.md`** in the repo root. It covers:

- Backend architecture (FastAPI + raw SQLite, no ORM)
- Forward-only SQL migrations
- Ingest pipeline (parse → extract quoted → dedup → thread → recompute)
- Key services (quotes, snip, duplicates, dates, audit, boilerplate, sanitization)
- Soft-delete model (30-day restore window)
- API surface (routers, Pydantic schemas)
- Frontend (React + TypeScript + Vite, typed API client)
- Code conventions (git allowlist, timestamps, JSON columns, mutations + audit)

## Data Retention

Uploaded `.eml`, `.msg`, `.pdf`, and `.docx` source containers can optionally be retained in a content-addressed store under `data/sources/` (controlled by `EMAILCHRONO_STORE_SOURCES` env var, default on). The app stores extracted email fields, duplicate-review decisions, audit events, and other metadata in `data/emailchrono.sqlite`; extracted attachments are stored under `data/attachments/<email_id>/`.

Permanent case deletion removes database rows and the owned attachment directories. Soft delete moves a case to trash and keeps its emails and attachments for restore. Soft-deleted items can be restored within 30 days.

## Security

The app runs locally on `127.0.0.1` with no authentication or multi-tenancy. Security features include:

- **Host allowlist**: only localhost addresses are accepted.
- **Unsafe-method header requirement**: `POST`, `PATCH`, `PUT`, and `DELETE` requests must include `X-EmailChrono-Local: 1` header to prevent cross-site script attacks.
- **Ingest resource limits**: individual files (100 MB), upload batches (500 MB), attachment blobs (50 MB), PDF pages (1000). Oversized items are skipped with warnings, not fatal.
- **Source blob validation**: SHA-256 content-addressing with path-traversal protection on store and import.
- **Excel formula escaping**: exported `.xlsx` workbooks have formula-like cell values prefixed with `'` to prevent injection.
- **HTML sanitization**: rendered email HTML allows only `cid:` and `data:` image sources; external URLs are blocked via restrictive iframe sandbox and Content-Security-Policy.

## Development

### Backend Dev Server (with auto-reload)

```powershell
.\scripts\dev-backend.ps1
```

Runs uvicorn with `--reload` on `http://127.0.0.1:8766` (different port from production). Code changes trigger automatic restart.

### Frontend Dev Server (with hot reload)

```powershell
.\scripts\dev-frontend.ps1
```

Runs Vite dev server on `http://127.0.0.1:5173` with hot module reload. All `/api` and `/healthz` requests proxy to the backend on `:8766`.

**To develop:** Run both servers in separate terminals. Access the frontend at `:5173`; it proxies backend requests automatically.

### Production Frontend Build

```powershell
.\scripts\build.ps1
```

Compiles TypeScript and builds the Vite bundle into `frontend/dist/`. The production launcher (`.\scripts\launch.ps1`) serves this bundle from the backend.
