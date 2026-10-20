"""FastAPI entrypoint for mail-core (sole backend)."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
    if not listener.wait_started(timeout=5):
        # Keep serving so operators can hit /ready; do not pretend LISTEN is up.
        logging.getLogger("mail_core.api").error(
            "outbox LISTEN not started within 5s; /ready will stay not_ready until LISTEN succeeds"
        )
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
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(accounts_router, dependencies=[Depends(require_auth)])
app.include_router(sse_router, prefix="/api", tags=["realtime"], dependencies=[Depends(require_auth)])
app.include_router(mail_router, dependencies=[Depends(require_auth)])


@lru_cache(maxsize=1)
def _code_schema_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    import mail_core.db as db_pkg

    here = Path(db_pkg.__file__).resolve().parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


class HealthOut(BaseModel):
    status: str
    service: str
    version: str
    schema_head: str | None


class ReadyOut(BaseModel):
    status: str
    schema_revision: str | None = None
    schema_head: str | None = None
    listener: bool | None = None
    reason: str | None = None


@app.get("/health", response_model=HealthOut)
def health(response: Response) -> HealthOut:
    token = os.environ.get("KKMAIL_INSTANCE_TOKEN")
    if token:
        response.headers["X-Instance-Token"] = token
    return HealthOut(status="ok", service="mail-core", version=__version__, schema_head=_code_schema_head())


@app.get("/ready", response_model=ReadyOut, responses={503: {"model": ReadyOut}})
def ready():
    """Readiness: DB reachable, schema at code head, outbox listener running."""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    from mail_core.db.session import get_engine
    from mail_core.realtime.listener import get_outbox_listener

    head = _code_schema_head()
    try:
        with get_engine().connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:
        body = ReadyOut(status="not_ready", schema_head=head, reason=f"database: {type(exc).__name__}")
        return JSONResponse(status_code=503, content=body.model_dump())
    listener = get_outbox_listener()
    # Thread alive-but-reconnecting is not ready; require a successful LISTEN.
    listener_ok = listener.listen_ready
    if rev != head:
        body = ReadyOut(status="not_ready", schema_revision=rev, schema_head=head, listener=listener_ok, reason="schema_out_of_date")
        return JSONResponse(status_code=503, content=body.model_dump())
    if not listener_ok:
        body = ReadyOut(status="not_ready", schema_revision=rev, schema_head=head, listener=False, reason="outbox_listener")
        return JSONResponse(status_code=503, content=body.model_dump())
    return ReadyOut(status="ready", schema_revision=rev, schema_head=head, listener=True)


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
        dist_root = _DIST.resolve()
        try:
            candidate = (_DIST / full_path).resolve()
            if candidate.is_relative_to(dist_root) and candidate.is_file():
                return FileResponse(candidate)
        except Exception:
            pass
        return FileResponse(_DIST / "index.html")
