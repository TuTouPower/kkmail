"""Backup package: PG dump + blob tar + checksums, optionally AES-GCM sealed."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import tarfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from mail_core.backup.crypto import (
    BackupCryptoError,
    decrypt_bytes,
    encrypt_bytes,
    load_backup_key,
    load_backup_keyring,
)
from mail_core.blobs.archive import blob_root
from mail_core.db.session import database_url

log = logging.getLogger("mail_core.backup")


@dataclass(frozen=True, slots=True)
class BackupManifest:
    created_at: str
    database_url_redacted: str
    blob_root: str
    members: dict[str, dict[str, str | int]]
    encrypted: bool = False
    backup_key_version: int | None = None
    note: str = "Encrypt with MAIL_CORE_BACKUP_KEY (separate from blob keys) before offsite copy."


@dataclass(frozen=True, slots=True)
class RestoreVerifyResult:
    ok: bool
    members_checked: int
    errors: list[str]
    backup_key_version: int | None = None


def _redact_url(url: str) -> str:
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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pg_dump_to(dest: Path, url: str) -> str:
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
    dest.write_text(
        "-- mail-core backup stub: pg_dump unavailable or failed\n"
        f"-- url={_redact_url(url)}\n"
        f"-- at={datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    return "sql_stub"


def _build_plain_dir(
    out: Path,
    *,
    url: str,
    root: Path,
    include_blobs: bool,
) -> BackupManifest:
    out.mkdir(parents=True, exist_ok=True)
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
    return BackupManifest(
        created_at=datetime.now(timezone.utc).isoformat(),
        database_url_redacted=_redact_url(url),
        blob_root=str(root),
        members=members,
        encrypted=False,
    )


def create_backup_package(
    output_dir: str | Path,
    *,
    include_blobs: bool = True,
    database_url_override: str | None = None,
    blobs_dir: Path | None = None,
    encrypt: bool | None = None,
) -> Path:
    """Write a plain backup directory, optionally seal to ``backup.kkbak``."""
    out = Path(output_dir)
    url = database_url_override or database_url()
    root = blobs_dir or blob_root()
    do_encrypt = encrypt if encrypt is not None else bool(
        os.environ.get("MAIL_CORE_BACKUP_KEY") or os.environ.get("MAIL_CORE_BACKUP_KEYS")
    )

    plain = out / "plain" if do_encrypt else out
    manifest = _build_plain_dir(plain, url=url, root=root, include_blobs=include_blobs)
    man_path = plain / "MANIFEST.json"
    man_path.write_text(json.dumps(asdict(manifest), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (plain / "MANIFEST.sha256").write_text(f"{_sha256_file(man_path)}  MANIFEST.json\n", encoding="utf-8")

    if not do_encrypt:
        log.info("backup package written to %s (plaintext)", out)
        return out

    key, version = load_backup_key()
    # Tar the plain directory into memory / temp then encrypt
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path in sorted(plain.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(plain)))
    sealed = encrypt_bytes(buf.getvalue(), key=key, key_version=version)
    out.mkdir(parents=True, exist_ok=True)
    kkbak = out / "backup.kkbak"
    kkbak.write_bytes(sealed)
    sealed_manifest = BackupManifest(
        created_at=manifest.created_at,
        database_url_redacted=manifest.database_url_redacted,
        blob_root=manifest.blob_root,
        members={
            "backup.kkbak": {"sha256": _sha256_file(kkbak), "size": kkbak.stat().st_size},
            **{f"plain/{k}": v for k, v in manifest.members.items()},
        },
        encrypted=True,
        backup_key_version=version,
        note=manifest.note,
    )
    (out / "MANIFEST.json").write_text(
        json.dumps(asdict(sealed_manifest), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "MANIFEST.sha256").write_text(
        f"{_sha256_file(out / 'MANIFEST.json')}  MANIFEST.json\n", encoding="utf-8"
    )
    # Remove plaintext working tree from the package root
    shutil.rmtree(plain, ignore_errors=True)
    log.info("encrypted backup written to %s", kkbak)
    return out


def verify_backup_package(
    package_dir: str | Path,
    *,
    env: dict[str, str] | None = None,
) -> RestoreVerifyResult:
    """Decrypt (if needed) and verify member checksums. Does not restore into PG."""
    root = Path(package_dir)
    errors: list[str] = []
    key_version: int | None = None
    work = root
    kkbak = root / "backup.kkbak"
    if kkbak.is_file():
        try:
            keyring = load_backup_keyring(env)
            plaintext, key_version = decrypt_bytes(kkbak.read_bytes(), keyring=keyring)
        except Exception as exc:
            return RestoreVerifyResult(ok=False, members_checked=0, errors=[f"decrypt failed: {exc}"])
        extract_dir = root / ".verify_extract"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r") as tar:
            tar.extractall(extract_dir, filter="data")
        work = extract_dir

    man_path = work / "MANIFEST.json"
    if not man_path.is_file():
        return RestoreVerifyResult(ok=False, members_checked=0, errors=["MANIFEST.json missing"], backup_key_version=key_version)
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    # Verify MANIFEST.sha256 if present
    sha_path = work / "MANIFEST.sha256"
    if sha_path.is_file():
        expected = sha_path.read_text(encoding="utf-8").split()[0]
        actual = _sha256_file(man_path)
        if expected != actual:
            errors.append(f"MANIFEST.sha256 mismatch: expected {expected}, got {actual}")

    checked = 0
    for name, meta in (manifest.get("members") or {}).items():
        # Skip nested plain/ aliases on sealed outer manifest
        if name.startswith("plain/"):
            continue
        if name == "backup.kkbak":
            continue
        path = work / name
        if not path.is_file():
            errors.append(f"missing member {name}")
            continue
        digest = _sha256_file(path)
        expected = str(meta.get("sha256") or "")
        if expected and digest != expected:
            errors.append(f"checksum mismatch for {name}")
        checked += 1

    if kkbak.is_file():
        shutil.rmtree(work, ignore_errors=True)

    return RestoreVerifyResult(
        ok=not errors,
        members_checked=checked,
        errors=errors,
        backup_key_version=key_version,
    )


def run_backup(*, output_dir: str | None = None, encrypt: bool | None = None) -> dict:
    dest = Path(output_dir or os.environ.get("MAIL_CORE_BACKUP_DIR") or "[REDACTED]mail-core-backup")
    path = create_backup_package(dest, encrypt=encrypt)
    verify = verify_backup_package(path)
    return {
        "status": "ok" if verify.ok else "verify_failed",
        "path": str(path),
        "files": sorted(p.name for p in path.iterdir() if p.name != ".verify_extract"),
        "verify": {
            "ok": verify.ok,
            "members_checked": verify.members_checked,
            "errors": verify.errors,
            "backup_key_version": verify.backup_key_version,
        },
    }
