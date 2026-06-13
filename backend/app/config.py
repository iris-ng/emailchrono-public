import os
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = Path(os.environ.get("EMAILCHRONO_DATA_DIR", ROOT_DIR / "data"))
ATTACHMENTS_DIR = DATA_DIR / "attachments"
SOURCES_DIR = DATA_DIR / "sources"
DB_PATH = DATA_DIR / "emailchrono.sqlite"
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
FRONTEND_DIST_DIR = ROOT_DIR / "frontend" / "dist"

# Capture original source bytes into the managed content-addressed store
# (SOURCES_DIR) at ingest. Content-addressing dedupes identical uploads; the
# cost is extra disk. Default on; set EMAILCHRONO_STORE_SOURCES=0 to disable.
STORE_SOURCES = os.environ.get("EMAILCHRONO_STORE_SOURCES", "1").lower() not in {"0", "false", "no"}

MAX_INGEST_FILE_BYTES = 100 * 1024 * 1024
MAX_INGEST_BATCH_BYTES = 500 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 1000

ALLOWED_HOSTS = {
    "127.0.0.1",
    "127.0.0.1:8765",
    "127.0.0.1:8766",
    "localhost",
    "localhost:8765",
    "localhost:8766",
    "testserver",
}
