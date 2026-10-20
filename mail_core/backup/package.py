"""Backup package stub: PostgreSQL dump + blob tree tar + checksums.

Produces a directory (or .tar.gz later) containing:
  - postgres.dump  (pg_dump custom format when pg_dump is available; else SQL stub)
  - blobs.tar      (blob root archive)
  - MANIFEST.json  (sizes, sha256 of members, created_at)
  - MANIFEST.sha256

Encryption of the backup package with a separate backup key is TODO
(architecture §10.2 / §11.1).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from mail_core.blobs.archive import blob_root
from mail_core.db.session import database_url

log = logging.getLogger("mail_core.backup")


@dataclass(frozen=True, slots=True)
class BackupManifest:
    created_at: str
    database_url_redacted: str
    blob_root: str
    members: dict[str, dict[str, str | int]]
    note: str = "Backup package stub — encrypt with a separate backup key before offsite copy."


def _redact_url(url: str) -> str:
    # hide password between :// and @
    if "://" in url and "@" in url:
        scheme, rest = url.split("://", 1)
        if "@" in rest and ":" in rest.split("@", 1)[0]:
            user = rest.split("@", 1)[0].split(":", 1)[0]
            host = rest.split("@", 1)[1]
            return f"{scheme}://{user}:***@{host}"
    return url


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pg_dump_to(dest: Path, url: str) -> str:
    """Return method used: custom | sql_stub."""
    dsn = url
    if dsn.startswith("postgresql+psycopg://"):
        dsn = "postgresql://" + dsn[len("postgresql+psycopg://") :]
    pg_dump = shutil.which("pg_dump")
    if pg_dump:
        try:
            subprocess.run(
                [pg_dump, "--format=custom", "--file", str(dest), dsn],
                check=True,
                capture_output=True,
            )
            return "custom"
        except subprocess.CalledProcessError as exc:
            log.warning("pg_dump failed: %s", exc.stderr.decode(errors="replace")[:500])
    # Stub placeholder so packaging still works in CI without pg_dump
    dest.write_text(
        "-- mail-core backup stub: pg_dump unavailable or failed\n"
        f"-- url={_redact_url(url)}\n"
        f"-- at={datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    return "sql_stub"


def create_backup_package(
    output_dir: str | Path,
    *,
    include_blobs: bool = True,
    database_url_override: str | None = None,
    blobs_dir: Path | None = None,
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    url = database_url_override or database_url()
    root = blobs_dir or blob_root()

    dump_path = out / "postgres.dump"
    dump_method = _pg_dump_to(dump_path, url)

    members: dict[str, dict[str, str | int]] = {
        "postgres.dump": {
            "sha256": _sha256_file(dump_path),
            "size": dump_path.stat().st_size,
            "method": dump_method,
        }
    }

    if include_blobs:
        tar_path = out / "blobs.tar"
        with tarfile.open(tar_path, "w") as tar:
            if root.exists():
                tar.add(root, arcname="blobs")
        members["blobs.tar"] = {
            "sha256": _sha256_file(tar_path),
            "size": tar_path.stat().st_size,
        }

    manifest = BackupManifest(
        created_at=datetime.now(timezone.utc).isoformat(),
        database_url_redacted=_redact_url(url),
        blob_root=str(root),
        members=members,
    )
    man_path = out / "MANIFEST.json"
    man_path.write_text(json.dumps(asdict(manifest), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    checksum = _sha256_file(man_path)
    (out / "MANIFEST.sha256").write_text(f"{checksum}  MANIFEST.json\n", encoding="utf-8")
    log.info("backup package written to %s", out)
    return out


def run_backup(*, output_dir: str | None = None) -> dict:
    dest = Path(output_dir or os.environ.get("MAIL_CORE_BACKUP_DIR") or "[REDACTED]mail-core-backup")
    path = create_backup_package(dest)
    return {"status": "ok", "path": str(path), "files": sorted(p.name for p in path.iterdir())}
