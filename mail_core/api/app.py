"""FastAPI entrypoint for mail-core (skeleton)."""

from __future__ import annotations

from fastapi import FastAPI

from mail_core import __version__

app = FastAPI(
    title="kkmail mail-core",
    version=__version__,
    description="Local-authoritative mail kernel API (greenfield). See docs/mail-core-architecture.md.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mail-core", "version": __version__}


@app.get("/ready")
def ready() -> dict[str, str]:
    """Liveness-only for now; DB readiness lands with schema milestone."""
    return {"status": "ready"}
