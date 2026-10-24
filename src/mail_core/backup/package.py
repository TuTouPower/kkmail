"""Backup package: PG dump + blob tar + checksums, optionally AES-GCM sealed."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urlunparse

from mail_core.backup.crypto import (
    BackupCryptoError,
    decrypt_bytes,
    decrypt_file,
    encrypt_bytes,
    encrypt_file,
    load_backup_key,
    load_backup_keyring,
)
from mail_core.blobs.archive import blob_root
from mail_core.db.session import database_url

log = logging.getLogger("mail_core.backup")

_MANIFEST_FILENAME = "MANIFEST.json"
_MANIFEST_CHECKSUM_FILENAME = "MANIFEST.sha256"


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
    if candidate.is_symlink():
        return None
    try:
        work_res = work.resolve(strict=False)
        cand_res = candidate.resolve(strict=False)
    except OSError:
        return None
    if cand_res != work_res and work_res not in cand_res.parents:
        return None
    return candidate


def _safe_rmtree(path: Path) -> None:
    """Safely remove a temporary directory created by this process without following symlinks."""
    try:
        if path.is_symlink():
            path.unlink()
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
    except OSError:
        pass


def _make_private_dir(path: Path) -> Path:
    """Create a private 0700 directory, refusing symlinks."""
    if path.is_symlink():
        raise BackupCryptoError(f"refusing to use symlink as private workspace: {path}")
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _set_private_file(path: Path) -> None:
    """Set file permissions to 0600."""
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _verify_manifest_file_checksum(man_path: Path, sha_path: Path, errors: list[str]) -> None:
    if not sha_path.is_file():
        errors.append(f"{sha_path.name} missing")
        return
    raw = sha_path.read_text(encoding="utf-8").strip()
    if not raw:
        errors.append(f"{sha_path.name} is empty")
        return
    parts = raw.split()
    if not parts:
        errors.append(f"{sha_path.name} invalid format")
        return
    expected = parts[0]
    if len(expected) != 64:
        errors.append(f"{sha_path.name} invalid sha256: {expected!r}")
        return
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
        env["PGCONNECT_TIMEOUT"] = os.environ.get("MAIL_CORE_PG_CONNECT_TIMEOUT", "10")
        if password is not None:
            env["PGPASSWORD"] = password
        else:
            env.pop("PGPASSWORD", None)
        dump_timeout = float(os.environ.get("MAIL_CORE_PG_DUMP_TIMEOUT", "300"))
        cmd = [
            pg_dump,
            "--format=custom",
            "--lock-wait-timeout=30000",
            "--file",
            str(dest),
            dsn,
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                env=env,
                timeout=dump_timeout,
            )
            return "custom"
        except subprocess.TimeoutExpired as exc:
            log.warning("pg_dump timed out after %ss", dump_timeout)
            if not allow_stub:
                raise RuntimeError(f"pg_dump timed out after {dump_timeout}s") from exc
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
    _make_private_dir(out)
    dump_path = out / "postgres.dump"
    dump_method = _pg_dump_to(dump_path, url, allow_stub=allow_dump_stub)
    _set_private_file(dump_path)
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
        _set_private_file(tar_path)
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
    if out.is_symlink():
        raise RuntimeError(f"refusing to use symlink as output directory: {out}")
    url = database_url_override or database_url()
    root = blobs_dir or blob_root()
    do_encrypt = encrypt if encrypt is not None else bool(
        os.environ.get("MAIL_CORE_BACKUP_KEY")
    )

    if not do_encrypt:
        _make_private_dir(out)
        manifest = _build_plain_dir(
            out, url=url, root=root, include_blobs=include_blobs, allow_dump_stub=allow_dump_stub
        )
        man_path = out / _MANIFEST_FILENAME
        man_path.write_text(json.dumps(asdict(manifest), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _set_private_file(man_path)
        sha_path = out / _MANIFEST_CHECKSUM_FILENAME
        sha_path.write_text(f"{_sha256_file(man_path)}  {_MANIFEST_FILENAME}\n", encoding="utf-8")
        _set_private_file(sha_path)

        # Clean up any stale sealed artifacts from previous runs
        for stale_name in ("backup.kkbak", "backup.kkbak.sha256"):
            stale_f = out / stale_name
            if stale_f.exists():
                stale_f.unlink()
        log.info("backup package written to %s (plaintext)", out)
        return out

    key, version = load_backup_key()
    _make_private_dir(out)

    plain_stage = out / f".stage_plain_{uuid.uuid4().hex}"
    _make_private_dir(plain_stage)
    tar_tmp = out / f".archive_{uuid.uuid4().hex}.tar"
    kkbak = out / "backup.kkbak"

    try:
        manifest = _build_plain_dir(
            plain_stage, url=url, root=root, include_blobs=include_blobs, allow_dump_stub=allow_dump_stub
        )
        man_path = plain_stage / _MANIFEST_FILENAME
        man_path.write_text(json.dumps(asdict(manifest), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _set_private_file(man_path)
        sha_path = plain_stage / _MANIFEST_CHECKSUM_FILENAME
        sha_path.write_text(f"{_sha256_file(man_path)}  {_MANIFEST_FILENAME}\n", encoding="utf-8")
        _set_private_file(sha_path)

        with tarfile.open(tar_tmp, mode="w") as tar:
            for path in sorted(plain_stage.rglob("*")):
                if path.is_symlink():
                    raise RuntimeError(f"refusing symlink in backup staging: {path}")
                if path.is_file() and path != tar_tmp:
                    tar.add(path, arcname=str(path.relative_to(plain_stage)))
        _set_private_file(tar_tmp)

        encrypt_file(tar_tmp, kkbak, key=key, key_version=version)

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
        out_man = out / _MANIFEST_FILENAME
        out_man.write_text(
            json.dumps(asdict(sealed_manifest), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        _set_private_file(out_man)
        out_sha = out / _MANIFEST_CHECKSUM_FILENAME
        out_sha.write_text(
            f"{_sha256_file(out_man)}  {_MANIFEST_FILENAME}\n", encoding="utf-8"
        )
        _set_private_file(out_sha)
        log.info("encrypted backup written to %s", kkbak)
        return out
    finally:
        _safe_rmtree(plain_stage)
        _safe_rmtree(tar_tmp)


_INNER_TAR_ALLOWLIST = _PLAIN_MEMBER_ALLOWLIST | {
    _MANIFEST_FILENAME,
    _MANIFEST_CHECKSUM_FILENAME,
}


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
        if not expected or len(expected) != 64:
            errors.append(f"invalid or missing sha256 for {name}")
        elif digest != expected:
            errors.append(f"checksum mismatch for {name}: expected {expected}, got {digest}")
        checked += 1
    return checked


def _extract_tar_file(tar_path: Path, extract_dir: Path, errors: list[str]) -> bool:
    """Extract inner backup tar from disk with path-traversal / allowlist checks."""
    try:
        with tarfile.open(tar_path, mode="r") as tar:
            for info in tar.getmembers():
                name = info.name
                if info.issym() or info.islnk():
                    errors.append(f"unsafe symlink or hardlink in tar: {name!r}")
                    return False
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
            for p in extract_dir.rglob("*"):
                if p.is_symlink():
                    errors.append(f"unexpected symlink after extract: {p.name!r}")
                    return False
                if p.is_file():
                    _set_private_file(p)
                elif p.is_dir():
                    try:
                        p.chmod(0o700)
                    except OSError:
                        pass
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

    outer_man = root / _MANIFEST_FILENAME
    is_sealed = False
    if outer_man.is_file():
        try:
            outer_data = json.loads(outer_man.read_text(encoding="utf-8"))
            is_sealed = bool(outer_data.get("encrypted"))
        except Exception:
            is_sealed = kkbak.is_file()
    else:
        is_sealed = kkbak.is_file()

    if is_sealed and kkbak.is_file():
        # --- Outer sealed integrity (previously skipped) ---
        if not outer_man.is_file():
            return RestoreVerifyResult(
                ok=False,
                members_checked=0,
                errors=[f"outer {_MANIFEST_FILENAME} missing"],
            )
        _verify_manifest_file_checksum(
            outer_man, root / _MANIFEST_CHECKSUM_FILENAME, errors
        )
        try:
            outer = json.loads(outer_man.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return RestoreVerifyResult(
                ok=False,
                members_checked=0,
                errors=[f"outer {_MANIFEST_FILENAME} invalid: {exc}"],
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

        extract_dir = root / f".verify_{uuid.uuid4().hex}"
        if extract_dir.is_symlink():
            errors.append(f"refusing symlink as verify extract directory: {extract_dir}")
            return RestoreVerifyResult(
                ok=False, members_checked=checked, errors=errors, backup_key_version=key_version
            )
        _make_private_dir(extract_dir)
        decrypted_tar = extract_dir / f".decrypted_{uuid.uuid4().hex}.tar"
        try:
            try:
                keyring = load_backup_keyring(env)
                key_version = decrypt_file(kkbak, decrypted_tar, keyring=keyring)
            except Exception as exc:
                errors.append(f"decrypt failed: {exc}")
                return RestoreVerifyResult(
                    ok=False, members_checked=checked, errors=errors, backup_key_version=key_version
                )
            if not _extract_tar_file(decrypted_tar, extract_dir, errors):
                return RestoreVerifyResult(
                    ok=False, members_checked=checked, errors=errors, backup_key_version=key_version
                )
            if decrypted_tar.exists():
                decrypted_tar.unlink()
            return _verify_plain_tree(
                extract_dir,
                checked=checked,
                errors=errors,
                key_version=key_version,
                allow_stub=allow_stub,
            )
        finally:
            _safe_rmtree(extract_dir)

    return _verify_plain_tree(
        root,
        checked=checked,
        errors=errors,
        key_version=key_version,
        allow_stub=allow_stub,
    )


def _verify_plain_tree(
    work: Path,
    *,
    checked: int,
    errors: list[str],
    key_version: int | None,
    allow_stub: bool,
) -> RestoreVerifyResult:
    man_path = work / _MANIFEST_FILENAME
    if not man_path.is_file():
        return RestoreVerifyResult(
            ok=False,
            members_checked=checked,
            errors=errors + [f"{_MANIFEST_FILENAME} missing"],
            backup_key_version=key_version,
        )
    try:
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return RestoreVerifyResult(
            ok=False,
            members_checked=checked,
            errors=errors + [f"{_MANIFEST_FILENAME} invalid: {exc}"],
            backup_key_version=key_version,
        )
    _verify_manifest_file_checksum(
        man_path, work / _MANIFEST_CHECKSUM_FILENAME, errors
    )
    members = manifest.get("members") or {}
    if "postgres.dump" not in members:
        errors.append("required member postgres.dump missing from manifest")
    checked += _check_plain_members(
        work, members, allow_stub=allow_stub, errors=errors
    )
    return RestoreVerifyResult(
        ok=not errors,
        members_checked=checked,
        errors=errors,
        backup_key_version=key_version,
    )


def run_backup(*, output_dir: str | None = None, encrypt: bool | None = None) -> dict:
    dest = Path(output_dir or os.environ.get("MAIL_CORE_BACKUP_DIR") or "[REDACTED]mail-core-backup")
    if dest.is_symlink():
        raise RuntimeError(f"refusing backup destination as symlink: {dest}")
    do_encrypt = True if encrypt is None else encrypt
    if do_encrypt:
        # Enforce strict encryption in production: refuse to run without backup keys
        load_backup_key()

    dest.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = dest.parent / f".staging_{dest.name}_{uuid.uuid4().hex}"
    if staging_dir.is_symlink():
        raise RuntimeError(f"refusing staging dir as symlink: {staging_dir}")
    _make_private_dir(staging_dir)
    try:
        path = create_backup_package(staging_dir, encrypt=do_encrypt)
        verify = verify_backup_package(path)
        if not verify.ok:
            _safe_rmtree(staging_dir)
            return {
                "status": "verify_failed",
                "path": str(dest),
                "files": [],
                "verify": {
                    "ok": False,
                    "members_checked": verify.members_checked,
                    "errors": verify.errors,
                    "backup_key_version": verify.backup_key_version,
                },
            }
        # Atomic replace: swap staging directory into dest
        old_dir = dest.parent / f".old_{dest.name}_{uuid.uuid4().hex}"
        if dest.exists():
            if dest.is_symlink():
                raise RuntimeError(f"refusing existing destination as symlink: {dest}")
            dest.rename(old_dir)
        try:
            staging_dir.rename(dest)
            if old_dir.exists():
                _safe_rmtree(old_dir)
        except Exception:
            if old_dir.exists():
                old_dir.rename(dest)
            raise
        return {
            "status": "ok",
            "path": str(dest),
            "files": sorted(p.name for p in dest.iterdir() if not p.name.startswith(".")),
            "verify": {
                "ok": True,
                "members_checked": verify.members_checked,
                "errors": verify.errors,
                "backup_key_version": verify.backup_key_version,
            },
        }
    finally:
        _safe_rmtree(staging_dir)


@dataclass(frozen=True, slots=True)
class RestoreResult:
    ok: bool
    database_restored: bool
    blobs_restored: int
    duration_seconds: float
    package_size_bytes: int
    errors: list[str]


def restore_backup_package(
    package_path: str | Path,
    *,
    target_database_url: str,
    target_blobs_dir: str | Path,
    keyring: dict[int, bytes] | None = None,
    allow_stub: bool = False,
    source_database_url: str | None = None,
) -> RestoreResult:
    """Restore a backup package into a dedicated disposable target database and blob directory.

    Verifies checksums and signatures before unpacking. Enforces destination safety guards.
    """
    begun = datetime.now(timezone.utc)
    pkg = Path(package_path).resolve()
    if pkg.is_dir():
        pkg_dir = pkg
    elif pkg.is_file():
        pkg_dir = pkg.parent
    else:
        raise FileNotFoundError(f"backup package not found: {pkg}")

    pkg_size = sum(f.stat().st_size for f in pkg_dir.glob("**/*") if f.is_file())

    # Guard AC-004: Prevent restoring onto the same source database
    if source_database_url:
        src_clean = _redact_url(source_database_url)
        tgt_clean = _redact_url(target_database_url)
        if src_clean == tgt_clean:
            raise RuntimeError(f"refusing to restore onto source database: {src_clean}")

    target_blobs = Path(target_blobs_dir).resolve()
    if target_blobs.is_symlink():
        raise RuntimeError(f"refusing target blobs dir as symlink: {target_blobs}")
    if any(part in ("..", ".") for part in Path(target_blobs_dir).parts):
        raise RuntimeError(f"path traversal detected in target blobs dir: {target_blobs_dir}")

    # Verify package first
    vr = verify_backup_package(pkg_dir, allow_stub=allow_stub)
    if not vr.ok:
        raise RuntimeError(f"backup package verification failed: {vr.errors}")

    temp_parent = pkg_dir.parent
    work_dir = temp_parent / f".restore_staging_{uuid.uuid4().hex}"
    _make_private_dir(work_dir)
    errors: list[str] = []
    blobs_restored = 0
    db_restored = False

    kkbak = pkg_dir / "backup.kkbak"
    try:
        # Decrypt if encrypted
        if kkbak.is_file():
            plain_tar = work_dir / "plain.tar.gz"
            keyring_to_use = keyring or load_backup_keyring()
            decrypt_file(kkbak, plain_tar, keyring=keyring_to_use)
            tar_to_extract = plain_tar
        else:
            # Check for plain tarball
            candidates = list(pkg_dir.glob("*.tar.gz"))
            if not candidates:
                raise RuntimeError("no backup archive file found in package directory")
            tar_to_extract = candidates[0]

        extract_dir = work_dir / "extracted"
        _make_private_dir(extract_dir)
        if not _extract_tar_file(tar_to_extract, extract_dir, errors):
            raise RuntimeError(f"tar extraction failed: {errors}")

        man_path = extract_dir / _MANIFEST_FILENAME
        if not man_path.is_file():
            raise RuntimeError(f"missing {_MANIFEST_FILENAME} in backup archive")
        manifest = json.loads(man_path.read_text(encoding="utf-8"))

        # Reject stubs unless allow_stub explicitly granted
        dump_meta = manifest.get("members", {}).get("postgres.dump", {})
        dump_fmt = dump_meta.get("method", "custom")
        if dump_fmt == "stub" and not allow_stub:
            raise RuntimeError("refusing to restore stub backup without allow_stub")

        # 1. Restore blobs if blobs.tar is present
        blobs_tar = extract_dir / "blobs.tar"
        if blobs_tar.is_file():
            target_blobs.mkdir(parents=True, exist_ok=True)
            with tarfile.open(blobs_tar, "r") as t:
                for member in t.getmembers():
                    if member.name.startswith("blobs/") and not member.name.endswith("/"):
                        rel_path = member.name[len("blobs/"):]
                        if not rel_path or any(part in ("..", ".") for part in Path(rel_path).parts):
                            continue
                        dest_file = target_blobs / rel_path
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        f = t.extractfile(member)
                        if f:
                            dest_file.write_bytes(f.read())
                            blobs_restored += 1

        # 2. Restore PostgreSQL dump
        dump_file = extract_dir / "postgres.dump"
        if not dump_file.is_file():
            raise RuntimeError("missing postgres.dump in backup archive")

        dsn, password = _libpq_dsn_and_password(target_database_url)
        pg_restore = shutil.which("pg_restore")
        if not pg_restore:
            raise RuntimeError("pg_restore executable not found on PATH")

        env = os.environ.copy()
        env.pop("PGPASSFILE", None)
        env["PGCONNECT_TIMEOUT"] = os.environ.get("MAIL_CORE_PG_CONNECT_TIMEOUT", "10")
        if password is not None:
            env["PGPASSWORD"] = password
        else:
            env.pop("PGPASSWORD", None)

        restore_timeout = float(os.environ.get("MAIL_CORE_PG_RESTORE_TIMEOUT", "300"))
        cmd = [
            pg_restore,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            dsn,
            str(dump_file),
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            env=env,
            timeout=restore_timeout,
        )
        if res.returncode != 0:
            err_msg = res.stderr.decode("utf-8", errors="replace")[:1000]
            log.warning("pg_restore returned code %d: %s", res.returncode, err_msg)
            if res.returncode > 1 or "FATAL" in err_msg or "error:" in err_msg.lower():
                errors.append(f"pg_restore failed: {err_msg}")
                raise RuntimeError(f"pg_restore failed ({res.returncode}): {err_msg}")

        db_restored = True
        duration = (datetime.now(timezone.utc) - begun).total_seconds()
        return RestoreResult(
            ok=True,
            database_restored=db_restored,
            blobs_restored=blobs_restored,
            duration_seconds=duration,
            package_size_bytes=pkg_size,
            errors=errors,
        )
    finally:
        _safe_rmtree(work_dir)
