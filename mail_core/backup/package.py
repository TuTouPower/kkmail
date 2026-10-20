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
from urllib.parse import quote, unquote, urlparse, urlunparse

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


# Members written into a plain backup directory (inner tar for sealed packages).
_PLAIN_MEMBER_ALLOWLIST = frozenset({"postgres.dump", "blobs.tar"})
# Outer sealed package directory may also list the ciphertext blob.
_OUTER_MEMBER_ALLOWLIST = frozenset({"backup.kkbak"}) | {f"plain/{m}" for m in _PLAIN_MEMBER_ALLOWLIST}


def _libpq_dsn_and_password(url: str) -> tuple[str, str | None]:
    """Return a libpq URI without password, plus the password (if any).

    Password must not appear on the pg_dump argv (visible via ps /proc cmdline).
    Callers pass it via PGPASSWORD (or a 0600 pgpass file).
    """
    dsn = url
    if dsn.startswith("postgresql+psycopg://"):
        dsn = "postgresql://" + dsn[len("postgresql+psycopg://") :]
    elif dsn.startswith("postgres+psycopg://"):
        dsn = "postgres://" + dsn[len("postgres+psycopg://") :]
    parsed = urlparse(dsn)
    # urlparse leaves percent-encoding in .password; libpq/PGPASSWORD need decoded bytes.
    password = unquote(parsed.password) if parsed.password is not None else None
    if password is None:
        return dsn, None
    # Rebuild netloc without password: user@host:port
    user = unquote(parsed.username) if parsed.username else ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    userinfo = quote(user, safe="") if user else ""
    auth = f"{userinfo}@" if userinfo or user else ""
    # IPv6 hosts need brackets
    if host and ":" in host and not host.startswith("["):
        host_part = f"[{host}]"
    else:
        host_part = host
    netloc = f"{auth}{host_part}{port}"
    safe = urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )
    return safe, password


def _safe_member_relpath(name: str, *, allowlist: frozenset[str]) -> str | None:
    """Return ``name`` if it is an allowlisted relative path with no traversal."""
    if not isinstance(name, str) or name not in allowlist:
        return None
    if name.startswith(("/", "\\")) or "\\" in name:
        return None
    parts = Path(name).parts
    if not parts or any(p in ("..", "", ".") for p in parts):
        return None
    if Path(*parts).as_posix() != name:
        return None
    return name


def _resolve_member_file(work: Path, name: str) -> Path | None:
    """Map an allowlisted member name to a file under ``work`` (no escape)."""
    safe = _safe_member_relpath(name, allowlist=_PLAIN_MEMBER_ALLOWLIST)
    if safe is None:
        return None
    candidate = work.joinpath(*Path(safe).parts)
    try:
        work_res = work.resolve(strict=False)
        cand_res = candidate.resolve(strict=False)
    except OSError:
        return None
    if cand_res != work_res and work_res not in cand_res.parents:
        return None
    return candidate


def _verify_manifest_file_checksum(man_path: Path, sha_path: Path, errors: list[str]) -> None:
    if not sha_path.is_file():
        errors.append(f"{sha_path.name} missing")
        return
    expected = sha_path.read_text(encoding="utf-8").split()[0]
    actual = _sha256_file(man_path)
    if expected != actual:
        errors.append(f"{sha_path.name} mismatch: expected {expected}, got {actual}")


def _pg_dump_to(dest: Path, url: str, *, allow_stub: bool = False) -> str:
    """Run pg_dump into ``dest``.

    On failure (missing binary or non-zero exit), raise unless ``allow_stub`` is set
    for offline unit/crypto drills. Stubs never verify as restoreable backups.

    The database password is passed via ``PGPASSWORD`` (never on argv).
    """
    dsn, password = _libpq_dsn_and_password(url)
    pg_dump = shutil.which("pg_dump")
    if pg_dump:
        env = os.environ.copy()
        # Prefer PGPASSWORD; also drop any inherited PGPASSFILE so a stale pgpass
        # cannot override the intended credentials for this dump.
        env.pop("PGPASSFILE", None)
        if password is not None:
            env["PGPASSWORD"] = password
        else:
            env.pop("PGPASSWORD", None)
        try:
            subprocess.run(
                [pg_dump, "--format=custom", "--file", str(dest), dsn],
                check=True,
                capture_output=True,
                env=env,
            )
            return "custom"
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode(errors="replace")[:500] if exc.stderr else str(exc)
            log.warning("pg_dump failed: %s", detail)
            if not allow_stub:
                raise RuntimeError(f"pg_dump failed: {detail}") from exc
    elif not allow_stub:
        raise RuntimeError("pg_dump binary not found on PATH")
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
    allow_dump_stub: bool = False,
) -> BackupManifest:
    out.mkdir(parents=True, exist_ok=True)
    dump_path = out / "postgres.dump"
    dump_method = _pg_dump_to(dump_path, url, allow_stub=allow_dump_stub)
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
    allow_dump_stub: bool = False,
) -> Path:
    """Write a plain backup directory, optionally seal to ``backup.kkbak``.

    ``allow_dump_stub`` is for offline unit/crypto drills only. Production callers
    must leave it false so a failed pg_dump cannot seal as a successful backup.
    """
    out = Path(output_dir)
    url = database_url_override or database_url()
    root = blobs_dir or blob_root()
    do_encrypt = encrypt if encrypt is not None else bool(
        os.environ.get("MAIL_CORE_BACKUP_KEY") or os.environ.get("MAIL_CORE_BACKUP_KEYS")
    )

    plain = out / "plain" if do_encrypt else out
    manifest = _build_plain_dir(
        plain, url=url, root=root, include_blobs=include_blobs, allow_dump_stub=allow_dump_stub
    )
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


_INNER_TAR_ALLOWLIST = _PLAIN_MEMBER_ALLOWLIST | {"MANIFEST.json", "MANIFEST.sha256"}


def _check_plain_members(
    work: Path,
    members: dict,
    *,
    allow_stub: bool,
    errors: list[str],
) -> int:
    """Verify allowlisted plain members under ``work``. Returns count checked."""
    checked = 0
    for name, meta in (members or {}).items():
        if name.startswith("plain/") or name == "backup.kkbak":
            # Outer sealed aliases — handled separately before decrypt.
            continue
        if _safe_member_relpath(name, allowlist=_PLAIN_MEMBER_ALLOWLIST) is None:
            errors.append(f"disallowed member name: {name!r}")
            continue
        path = _resolve_member_file(work, name)
        if path is None or not path.is_file():
            errors.append(f"missing member {name}")
            continue
        method = meta.get("method")
        if method == "sql_stub" and not allow_stub:
            errors.append(
                f"{name} is sql_stub (pg_dump failed or skipped); backup is not restoreable"
            )
        digest = _sha256_file(path)
        expected = str(meta.get("sha256") or "")
        if expected and digest != expected:
            errors.append(f"checksum mismatch for {name}")
        checked += 1
    return checked


def _extract_plain_tar(plaintext: bytes, extract_dir: Path, errors: list[str]) -> bool:
    """Extract inner backup tar with path-traversal / allowlist checks."""
    try:
        with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r") as tar:
            for info in tar.getmembers():
                name = info.name
                if name.endswith("/"):
                    # Directory entries: only empty path or prefixes of allowlisted files.
                    base = name.rstrip("/")
                    if base and (
                        ".." in Path(base).parts
                        or base.startswith("/")
                        or not any(a == base or a.startswith(base + "/") for a in _INNER_TAR_ALLOWLIST)
                    ):
                        errors.append(f"unsafe tar member: {name!r}")
                        return False
                    continue
                if name not in _INNER_TAR_ALLOWLIST or ".." in Path(name).parts or name.startswith("/"):
                    errors.append(f"unsafe or unexpected tar member: {name!r}")
                    return False
            tar.extractall(extract_dir, filter="data")
    except tarfile.TarError as exc:
        errors.append(f"inner tar extract failed: {exc}")
        return False
    return True


def verify_backup_package(
    package_dir: str | Path,
    *,
    env: dict[str, str] | None = None,
    allow_stub: bool = False,
) -> RestoreVerifyResult:
    """Decrypt (if needed) and verify member checksums. Does not restore into PG.

    For sealed packages, the outer ``MANIFEST.json`` / ``MANIFEST.sha256`` and the
    ``backup.kkbak`` digest are checked before decrypt. Inner member names are
    allowlisted (no ``..`` / absolute paths).
    """
    root = Path(package_dir)
    errors: list[str] = []
    key_version: int | None = None
    checked = 0
    kkbak = root / "backup.kkbak"
    extract_dir: Path | None = None

    if kkbak.is_file():
        # --- Outer sealed integrity (previously skipped) ---
        outer_man = root / "MANIFEST.json"
        if not outer_man.is_file():
            return RestoreVerifyResult(
                ok=False, members_checked=0, errors=["outer MANIFEST.json missing"]
            )
        _verify_manifest_file_checksum(outer_man, root / "MANIFEST.sha256", errors)
        try:
            outer = json.loads(outer_man.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return RestoreVerifyResult(
                ok=False, members_checked=0, errors=[f"outer MANIFEST.json invalid: {exc}"]
            )
        outer_members = outer.get("members") or {}
        meta = outer_members.get("backup.kkbak") or {}
        expected_kk = str(meta.get("sha256") or "")
        actual_kk = _sha256_file(kkbak)
        if not expected_kk:
            errors.append("outer manifest missing backup.kkbak sha256")
        elif actual_kk != expected_kk:
            errors.append(
                f"checksum mismatch for backup.kkbak: expected {expected_kk}, got {actual_kk}"
            )
            return RestoreVerifyResult(
                ok=False, members_checked=checked, errors=errors, backup_key_version=None
            )
        else:
            checked += 1
        for name in outer_members:
            if _safe_member_relpath(name, allowlist=_OUTER_MEMBER_ALLOWLIST) is None:
                errors.append(f"disallowed outer member name: {name!r}")

        try:
            keyring = load_backup_keyring(env)
            plaintext, key_version = decrypt_bytes(kkbak.read_bytes(), keyring=keyring)
        except Exception as exc:
            errors.append(f"decrypt failed: {exc}")
            return RestoreVerifyResult(
                ok=False, members_checked=checked, errors=errors, backup_key_version=key_version
            )
        extract_dir = root / ".verify_extract"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True)
        if not _extract_plain_tar(plaintext, extract_dir, errors):
            shutil.rmtree(extract_dir, ignore_errors=True)
            return RestoreVerifyResult(
                ok=False, members_checked=checked, errors=errors, backup_key_version=key_version
            )
        work = extract_dir
    else:
        work = root

    man_path = work / "MANIFEST.json"
    if not man_path.is_file():
        if extract_dir is not None:
            shutil.rmtree(extract_dir, ignore_errors=True)
        return RestoreVerifyResult(
            ok=False,
            members_checked=checked,
            errors=errors + ["MANIFEST.json missing"],
            backup_key_version=key_version,
        )
    try:
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        if extract_dir is not None:
            shutil.rmtree(extract_dir, ignore_errors=True)
        return RestoreVerifyResult(
            ok=False,
            members_checked=checked,
            errors=errors + [f"MANIFEST.json invalid: {exc}"],
            backup_key_version=key_version,
        )
    _verify_manifest_file_checksum(man_path, work / "MANIFEST.sha256", errors)

    checked += _check_plain_members(
        work, manifest.get("members") or {}, allow_stub=allow_stub, errors=errors
    )

    if extract_dir is not None:
        shutil.rmtree(extract_dir, ignore_errors=True)

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
