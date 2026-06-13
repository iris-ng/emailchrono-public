# Security Policy

**Last Updated**: 2026-06-13

This document outlines the security model and mitigations in emailchrono.

## Threat Model

Emailchrono is a **local, single-user application** that runs on `127.0.0.1` with no authentication or multi-tenancy. The threat model assumes:

- **No external network exposure**: the app is localhost-only by design (host allowlist enforced in middleware).
- **No authentication**: anyone with network access to the machine (or ability to script browser requests) can interact with the app.
- **Untrusted data**: email files uploaded by users may contain malicious/malformed data; the app must not crash or allow code injection.

## Security Mitigations

### 1. Host Allowlist & Unsafe-Method Header

**Issue**: Localhost cross-site request forgery (CSRF) via malicious browser tabs or websites served on loopback.

**Mitigation**:
- `app/main.py` enforces host allowlist (`ALLOWED_HOSTS`) containing only `127.0.0.1` and `localhost` variants.
- Unsafe HTTP methods (`POST`, `PATCH`, `PUT`, `DELETE`) require `X-EmailChrono-Local: 1` header.
- Frontend client (`frontend/src/api/client.ts`) automatically includes this header for all non-GET requests.
- This prevents scripts from other domains/tabs from issuing state-changing requests.

### 2. Ingest Resource Limits

**Issue**: Malicious or malformed uploads could exhaust memory or CPU during parsing.

**Mitigation**:
- `app/config.py` defines central limits:
  - `MAX_INGEST_FILE_BYTES` (100 MB): individual file size cap
  - `MAX_INGEST_BATCH_BYTES` (500 MB): total upload batch size cap
  - `MAX_ATTACHMENT_BYTES` (50 MB): attachment blob size cap
  - `MAX_PDF_PAGES` (1000): PDF page count cap
- `app/api/ingest.py` validates file sizes in-flight before reading full content; oversized files are rejected with HTTP 413.
- `app/services/ingest.py` validates sizes before parsing; oversized files are marked as skipped (not fatal to the job).
- `app/parsers/pdf.py` rejects PDFs with page count exceeding `MAX_PDF_PAGES` before text extraction.
- Attachment blobs exceeding `MAX_ATTACHMENT_BYTES` are skipped with a warning; the email is still ingested.

### 3. Source Blob Path Traversal

**Issue**: Malicious `.ecz` bundles could write files outside `data/sources/` directory.

**Mitigation**:
- `app/services/source_store.py` implements `is_valid_sha256()` to validate blob names as exact 64-char hex strings.
- `store_source()` checks SHA format before path construction; invalid hashes raise `ValueError`.
- Path is canonicalized (`resolve()`) and checked to ensure it stays within `data/sources/` root.
- `app/services/transfer.py` `import_bundle()` calls `_validate_source_blobs()` which:
  - Rejects blob paths with backslashes (Windows path separator).
  - Rejects blob names containing `/`, `\`, `:`, `..`, or `.`.
  - Validates SHA-256 hex format before writing.
  - Verifies blob content hash matches filename before storing.
- Invalid or tampered blobs are rejected with `ImportError_`.

### 4. Excel Formula Injection

**Issue**: User-controlled email data (subject, sender, etc.) exported to `.xlsx` could contain cell formulas (`=cmd()`, etc.) executable by Excel/Calc.

**Mitigation**:
- `app/services/transfer.py` `_build_chronology_xlsx()` calls `safe_excel_text()` on all cell values.
- `safe_excel_text()` prefixes values starting with `=`, `+`, `-`, `@`, tab, CR, or LF (or those chars after leading spaces) with a single quote.
- This forces Excel to treat the cell as text, not a formula.
- Applied to all user-controlled columns: `doc_id`, `date_utc`, `from_addr`, `subject`, `body_text`, `source_file_display`, `notes`, `message_id`, `source_kind`, `tags`.

### 5. Remote Resource in Rendered Email HTML

**Issue**: Rendered email HTML could contain remote image URLs (`<img src="https://...">`) that leak user's IP/case metadata to external servers on first open.

**Mitigation**:
- `app/services/sanitize.py` uses custom `_allow_img_attribute()` handler for `<img>` tags:
  - Only allows `src="cid:..."` (embedded content-ID images) and `src="data:..."` (data URIs).
  - Rejects all `http://` and `https://` URLs.
  - Other attributes (`alt`, `title`, `height`, `width`) are allowed.
- `frontend/src/components/EmailHtmlFrame.tsx` renders sanitized HTML in an `<iframe>` with:
  - Restrictive `sandbox` attribute (only `allow-same-origin`; removed `allow-popups` and `allow-popups-to-escape-sandbox`).
  - Strict Content-Security-Policy header:
    - `default-src 'none'` — block all by default.
    - `img-src cid: data:` — only embedded/data images.
    - `style-src 'unsafe-inline'` — allow inline CSS (from sanitized email).
    - `script-src 'none'`, `object-src 'none'`, `form-action 'none'`, `connect-src 'none'` — no scripts, objects, forms, or network requests.

### 6. Bundle Integrity on Import

**Issue**: Imported `.ecz` bundles could be tampered with (blobs replaced, emails altered, etc.) without detection.

**Mitigation**:
- `app/services/transfer.py` `_validate_email_source_refs()` ensures all `source_blob_sha256` references in imported emails are valid SHA-256 hashes.
- Source blobs are re-hashed on extraction to detect corruption:
  ```python
  if hashlib.sha256(content).hexdigest().lower() != sha.lower():
      raise ImportError_("Malformed source blob in bundle")
  ```
- Manifest version is checked to ensure forward compatibility.
- Invalid bundles raise `ImportError_` and abort the import.

## Limitations & Known Issues

- **No audit of deleted items**: soft-deleted emails remain in the database indefinitely; there is no purge mechanism for the 30-day restore window.
- **No TLS/encryption**: data at rest is plain SQLite and unencrypted files. If disk is compromised, emails are readable.
- **No user-level access control**: anyone with localhost access (or ability to script requests) can read/modify all cases and emails.
- **PDF parsing**: relies on `pdfplumber` and `python-docx` libraries, which may have parsing vulnerabilities. PDFs are still extracted/stored even if parsing is disabled.

## Reporting Issues

This is a single-user, local-only app with no public exposure. For security questions or findings, review the code or contact the maintainer directly.
