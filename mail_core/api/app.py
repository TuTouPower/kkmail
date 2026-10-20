"""FastAPI entrypoint for mail-core (sole backend)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from mail_core import __version__
from mail_core.api.accounts import router as accounts_router
from mail_core.api.auth_routes import router as auth_router
from mail_core.api.deps import require_auth
from mail_core.api.mail import router as mail_router
from mail_core.api.sse import router as sse_router


def _frontend_dist() -> Path | None:
    env = os.environ.get("KKMAIL_FRONTEND_DIST", "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    root = Path(__file__).resolve().parents[2]
    candidates.append(root / "frontend" / "dist")
    for c in candidates:
        if c.is_dir() and (c / "index.html").is_file():
            return c
    return None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from mail_core.blobs.crypto import load_keyring_from_env
    from mail_core.realtime.listener import start_outbox_listener, stop_outbox_listener
    from mail_core.security.auth import validate_auth_config

    load_keyring_from_env()
    validate_auth_config()

    listener = start_outbox_listener()
    listener.wait_started(timeout=5)
    try:
        yield
    finally:
        stop_outbox_listener()


app = FastAPI(
    title="kkmail mail-core",
    version=__version__,
    description="Local-authoritative mail kernel (sole backend).",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5000",
        "http://localhost:5000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(accounts_router, dependencies=[Depends(require_auth)])
app.include_router(sse_router, prefix="/api", tags=["realtime"], dependencies=[Depends(require_auth)])
app.include_router(mail_router, dependencies=[Depends(require_auth)])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mail-core", "version": __version__}


@app.get("/ready")
def ready():
    """Liveness for orchestrators: requires DB connectivity."""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    from mail_core.db.session import get_engine

    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "database", "detail": str(exc)[:200]},
        )
    return {"status": "ready"}


_DIST = _frontend_dist()
if _DIST is not None:
    assets = _DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/")
    def spa_index():
        return FileResponse(_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        # Do not swallow API/health
        if full_path.startswith(("api/", "health", "ready", "docs", "openapi.json", "assets/")):
            from fastapi import HTTPException

            raise HTTPException(404)
        candidate = _DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
