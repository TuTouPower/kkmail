"""FastAPI entrypoint for mail-core."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mail_core import __version__
from mail_core.api.auth_routes import router as auth_router
from mail_core.api.deps import require_auth
from mail_core.api.mail import router as mail_router
from mail_core.api.sse import router as sse_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from mail_core.blobs.crypto import load_keyring_from_env
    from mail_core.realtime.listener import start_outbox_listener, stop_outbox_listener
    from mail_core.security.auth import validate_auth_config

    # Fail fast: refuse to serve without blob keys or auth config.
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
    description="Local-authoritative mail kernel API (greenfield). See docs/mail-core-architecture.md.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:5000", "http://localhost:5000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(sse_router, prefix="/api", tags=["realtime"], dependencies=[Depends(require_auth)])
app.include_router(mail_router, dependencies=[Depends(require_auth)])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mail-core", "version": __version__}


@app.get("/ready")
def ready() -> dict[str, str]:
    # Commit 4 will probe DB; keep shape stable.
    return {"status": "ready"}
