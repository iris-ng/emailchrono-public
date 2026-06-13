from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from . import db
from .api import attachments, cases, emails, ingest, tags, transfer
from .config import ALLOWED_HOSTS, FRONTEND_DIST_DIR

LOCAL_HEADER = "x-emailchrono-local"
UNSAFE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


class HostAllowlistMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "").lower()
        if host and host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "Host not allowed"}, status_code=400)
        if request.method.upper() in UNSAFE_METHODS and request.headers.get(LOCAL_HEADER) != "1":
            return JSONResponse({"detail": "Local request header required"}, status_code=403)
        return await call_next(request)


class SPAStaticFiles(StaticFiles):
    """Serve the built SPA, falling back to index.html for client-side routes.

    A hard refresh on a route like /cases/18 asks the server for that path
    directly; without this fallback StaticFiles returns 404 ("detail: Not
    Found"). We return index.html so React Router can resolve the route.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # Don't mask genuine API 404s, and only rescue missing routes.
            if exc.status_code == 404 and not path.startswith("api"):
                return await super().get_response("index.html", scope)
            raise


def create_app() -> FastAPI:
    db.init_db()
    app = FastAPI(title="Chronology")
    app.add_middleware(HostAllowlistMiddleware)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    app.include_router(cases.router)
    app.include_router(ingest.router)
    app.include_router(emails.router)
    app.include_router(attachments.router)
    app.include_router(tags.router)
    app.include_router(transfer.router)

    if Path(FRONTEND_DIST_DIR).exists():
        app.mount("/", SPAStaticFiles(directory=FRONTEND_DIST_DIR, html=True), name="frontend")

    return app


app = create_app()
