"""FastAPI entrypoint for mail-core (sole backend)."""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mail_core import __version__
from mail_core.api.accounts import router as accounts_router
from mail_core.api.auth_routes import router as auth_router
from mail_core.api.deps import require_auth
from mail_core.api.mail import router as mail_router
from mail_core.api.oauth_routes import router as oauth_router
from mail_core.api.sse import router as sse_router


_RESERVED_SPA_ROOTS = frozenset({"api", "health", "ready", "docs", "openapi.json", "assets"})


def _is_reserved_spa_path(full_path: str) -> bool:
    return full_path.partition("/")[0] in _RESERVED_SPA_ROOTS


def _resolve_spa_candidate(dist_root: Path, full_path: str) -> Path | None:
    try:
        candidate = (dist_root / full_path).resolve()
        if candidate.is_relative_to(dist_root) and candidate.is_file():
            return candidate
    except Exception as exc:
        logging.getLogger("mail_core.api").debug("SPA fallback path resolution failed (%s)", type(exc).__name__)
    return None


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
    from mail_core.logging_config import configure_logging
    from mail_core.realtime.listener import start_outbox_listener, stop_outbox_listener
    from mail_core.security.auth import validate_auth_config

    configure_logging(service_name="mail-core-api")
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

def _install_proxy_headers(app: FastAPI, forwarded_allow_ips: str) -> None:
    trusted = [host.strip() for host in forwarded_allow_ips.split(",") if host.strip()]
    if not trusted:
        return
    try:
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    except ImportError:
        logging.getLogger("mail_core.api").error(
            "MAIL_CORE_FORWARDED_ALLOW_IPS is set but uvicorn ProxyHeadersMiddleware could not be imported; "
            "forwarded headers remain disabled"
        )
        return
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted)


_forwarded_allow_ips = (os.environ.get("MAIL_CORE_FORWARDED_ALLOW_IPS") or "").strip()
_install_proxy_headers(app, _forwarded_allow_ips)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    # A313: credentialed CORS must not wildcard methods/headers; only the
    # methods and headers the SPA actually uses are allowed.
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
)


_SPA_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'"
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # A284: HSTS only when the request actually arrived over HTTPS. When
    # MAIL_CORE_FORWARDED_ALLOW_IPS is configured, ProxyHeadersMiddleware
    # has already folded a trusted X-Forwarded-Proto into url.scheme;
    # a raw forwarded header from an untrusted peer is never consulted.
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # A284: HTML responses (the SPA shell and its fallback pages) get a
    # default-src 'self' CSP; responses that set their own stricter CSP
    # (e.g. the OAuth callback page) keep it.
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers.setdefault("Content-Security-Policy", _SPA_CSP)
    return response


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    import uuid
    from mail_core.logging_config import reset_trace_id, set_trace_id

    req_id = request.headers.get("X-Request-ID") or request.headers.get("X-Trace-ID")
    if not req_id or re.fullmatch(r"[A-Za-z0-9._-]{1,64}", req_id) is None:
        req_id = f"req_{uuid.uuid4().hex[:10]}"
    token = set_trace_id(req_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response
    finally:
        reset_trace_id(token)


app.include_router(auth_router)
app.include_router(oauth_router)
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
    worker: bool | None = None
    reason: str | None = None


@app.get("/health", response_model=HealthOut)
def health(response: Response) -> HealthOut:
    token = os.environ.get("KKMAIL_INSTANCE_TOKEN")
    if token:
        response.headers["X-Instance-Token"] = token
    return HealthOut(status="ok", service="mail-core", version=__version__, schema_head=_code_schema_head())


@app.get("/ready", response_model=ReadyOut, responses={503: {"model": ReadyOut}})
def ready():
    """Readiness: DB reachable, schema at code head, outbox listener running, worker active."""
    from fastapi.responses import JSONResponse

    from mail_core.mail.storage.health import get_current_schema_revision
    from mail_core.realtime.listener import get_outbox_listener

    head = _code_schema_head()
    try:
        rev = get_current_schema_revision()
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

    worker_ok = None
    try:
        from mail_core.db.session import get_session_factory
        from mail_core.worker.heartbeat import get_worker_heartbeats

        Session = get_session_factory()
        with Session() as session:
            worker_ok, _, _ = get_worker_heartbeats(session)
    except Exception:
        pass

    if os.environ.get("MAIL_CORE_REQUIRE_WORKER_READY") == "1" and not worker_ok:
        body = ReadyOut(
            status="not_ready",
            schema_revision=rev,
            schema_head=head,
            listener=listener_ok,
            worker=False,
            reason="worker_not_running",
        )
        return JSONResponse(status_code=503, content=body.model_dump())

    return ReadyOut(status="ready", schema_revision=rev, schema_head=head, listener=True, worker=worker_ok)


@app.get("/api/system/health")
@app.get("/health/metrics", include_in_schema=False)
def system_health():
    """Lightweight operational and business health metrics."""
    from mail_core.db.session import get_session_factory
    from mail_core.system_metrics import get_system_health_metrics

    Session = get_session_factory()
    with Session() as session:
        return get_system_health_metrics(session).model_dump()


_DIST = _frontend_dist()
if _DIST is not None:
    assets = _DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/", include_in_schema=False)
    def spa_index():
        return FileResponse(_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        # Do not swallow API/health.
        if _is_reserved_spa_path(full_path):
            from fastapi import HTTPException

            raise HTTPException(404)
        candidate = _resolve_spa_candidate(_DIST.resolve(), full_path)
        if candidate is not None:
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
