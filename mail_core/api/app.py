"""FastAPI entrypoint for mail-core."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from mail_core import __version__
from mail_core.api.mail import router as mail_router
from mail_core.api.sse import router as sse_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from mail_core.realtime.listener import start_outbox_listener, stop_outbox_listener

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
app.include_router(sse_router, prefix="/api", tags=["realtime"])
app.include_router(mail_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mail-core", "version": __version__}


@app.get("/ready")
def ready() -> dict[str, str]:
    return {"status": "ready"}
