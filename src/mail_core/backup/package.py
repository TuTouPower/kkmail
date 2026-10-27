"""Backup package: PG dump + blob tar + checksums, optionally AES-GCM sealed."""

from __future__ import annotations

import errno
import hashlib
import ipaddress
import json
import logging
import math
import os
import shutil
import stat
import subprocess
import tarfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, unquote, urlparse, urlunparse

from sqlalchemy.engine import make_url

from mail_core.backup.crypto import (
    BackupCryptoError,
    decrypt_file,
    encrypt_file,
    load_backup_key,
    load_backup_keyring,
)
from mail_core.blobs.archive import blob_root
from mail_core.blobs.crypto import (
    MAGIC as _BLOB_MAGIC,
    BlobCryptoError,
    iter_unwrap,
    load_keyring_from_env,
)
from mail_core.db.session import database_url

log = logging.getLogger("mail_core.backup")

_MANIFEST_FILENAME = "MANIFEST.json"
_MANIFEST_CHECKSUM_FILENAME = "MANIFEST.sha256"
_SQL_STUB_METHOD = "sql_stub"


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


class PgDumpError(RuntimeError):
    """Raised when pg_dump is unavailable or cannot create a database dump."""


def _timeout_from_env(name: str, default: float = 300.0) -> float:
    """Parse a timeout env var, falling back to ``default`` on bad input.

    A malformed operator setting must not surface as a bare ``ValueError``
    from ``float()`` (callers expect ``PgDumpError``/``RuntimeError``-family
    failures or success), so unparsable, non-finite and non-positive values
    fall back to the default with a warning.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        log.warning("invalid %s=%r; falling back to %ss timeout", name, raw, default)
        return default
    if not math.isfinite(value) or value <= 0:
        log.warning("invalid %s=%r; falling back to %ss timeout", name, raw, default)
        return default
    return value


def _redact_url(url: str) -> str:
    """Return a package-safe database identifier: scheme, db name, fingerprint.

    Backup packages are copied offsite, so the identifier must not reveal the
    deployment topology (username, host, port or password). The fingerprint
    is taken over the connection identity without the password, so distinct
    databases remain distinguishable without disclosing where they live.
    """
    try:
        parsed = make_url(url)
    except Exception:
        return "***"
    database = parsed.database or ""
    if not database and not parsed.host:
        return "***"
    scheme = parsed.drivername.split("+", 1)[0] if parsed.drivername else "postgresql"
    identity = (
        f"{parsed.drivername}://{parsed.username or ''}@"
        f"{parsed.host or ''}:{parsed.port or ''}/{database}"
    )
    fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"{scheme}://***@***/{database}#sha256:{fingerprint}"


# Logical name recorded in manifests instead of the absolute blob path;
# the real path stays local (backup log lines / restore operation log).
_MANIFEST_BLOB_LOGICAL_NAME = "blobs"


@contextmanager
def _backup_destination_lock(dest: Path) -> Iterator[None]:
    lock_path = dest.with_name(f".{dest.name}.lock")
    if os.name == "nt" and lock_path.is_symlink():
        raise RuntimeError(f"refusing backup lock symlink: {lock_path}")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError(f"refusing non-file backup lock: {lock_path}")
        if os.name != "nt":
            os.fchmod(fd, 0o600)
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            while True:
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EDEADLK, errno.EAGAIN):
                        raise
                    time.sleep(0.05)
            try:
                yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def _ensure_backup_key_separate_from_blobs(backup_key: bytes) -> None:
    if not (os.environ.get("MAIL_CORE_BLOB_KEYS") or os.environ.get("MAIL_CORE_BLOB_KEY_V1")):
        return
    try:
        blob_keyring = load_keyring_from_env()
    except BlobCryptoError as exc:
        raise BackupCryptoError(f"cannot validate backup key separation: {exc}") from exc
    if backup_key in blob_keyring.keys.values():
        raise BackupCryptoError("backup key must differ from blob keys")


@dataclass(frozen=True, slots=True)
class DatabaseIdentity:
    system_identifier: str | None
    database_oid: int | None
    database_name: str


def _restore_database_identity(url: str) -> tuple[str, str, int, str]:
    """Return normalized PostgreSQL connection identity without credentials or username."""
    try:
        parsed = make_url(url)
    except Exception:
        raise RuntimeError("refusing to restore with an invalid PostgreSQL URL") from None

    scheme = parsed.drivername.lower().split("+", 1)[0]
    if scheme not in {"postgres", "postgresql"}:
        raise RuntimeError("refusing to restore with a non-PostgreSQL URL")
    identity_query = {key.lower() for key in parsed.query}
    if identity_query & {"host", "hostaddr", "port", "dbname", "database", "user", "service", "servicefile"}:
        raise RuntimeError("refusing to restore with identity-changing URL query parameters")
    if not parsed.host or not parsed.database:
        raise RuntimeError("refusing to restore with an incomplete PostgreSQL URL")

    host = parsed.host.strip().rstrip(".")
    if "," in host:
        raise RuntimeError("refusing to restore with a multi-host PostgreSQL URL")
    try:
        host = ipaddress.ip_address(host).compressed.lower()
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise RuntimeError("refusing to restore with an invalid PostgreSQL host") from None

    try:
        port = parsed.port
    except ValueError:
        raise RuntimeError("refusing to restore with an invalid PostgreSQL port") from None
    if port is None:
        port = 5432
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "127.0.0.1"
    return "postgresql", host, port, parsed.database


def _read_database_identity(url: str) -> DatabaseIdentity:
    """Connect to PostgreSQL database and query cluster system_identifier and database OID."""
    dsn, password = _libpq_dsn_and_password(url)
    import psycopg

    conn_kwargs = {"autocommit": True, "connect_timeout": 5}
    if password is not None:
        conn_kwargs["password"] = password
    try:
        with psycopg.connect(dsn, **conn_kwargs) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT oid, datname FROM pg_database WHERE datname = current_database()")
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("failed to query database identity: current_database not found")
                db_oid, db_name = row[0], row[1]

                sys_id = None
                try:
                    cur.execute("SELECT system_identifier::text FROM pg_control_system()")
                    sys_row = cur.fetchone()
                    if sys_row:
                        sys_id = str(sys_row[0])
                except Exception:
                    pass

                return DatabaseIdentity(
                    system_identifier=sys_id,
                    database_oid=int(db_oid) if db_oid is not None else None,
                    database_name=str(db_name),
                )
    except Exception as exc:
        raise RuntimeError(f"failed to inspect database identity: {exc}") from None


def _assert_target_database_is_empty(target_database_url: str) -> None:
    dsn, password = _libpq_dsn_and_password(target_database_url)
    import psycopg

    conn_kwargs = {"autocommit": True, "connect_timeout": 5}
    if password is not None:
        conn_kwargs["password"] = password
    try:
        with psycopg.connect(dsn, **conn_kwargs) as conn:
            with conn.cursor() as cur:
                # Counting tables alone is not enough: a database holding
                # only views, sequences, functions or extensions (with zero
                # tables, or only empty ones) is still not a fresh restore
                # target. Require no user-schema objects at all.
                cur.execute(
                    "SELECT "
                    "(SELECT count(*) FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                    "AND n.nspname NOT LIKE 'pg_toast%' "
                    "AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')), "
                    "(SELECT count(*) FROM pg_catalog.pg_proc p "
                    "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
                    "AND n.nspname NOT LIKE 'pg_toast%'), "
                    "(SELECT count(*) FROM pg_catalog.pg_extension "
                    "WHERE extname <> 'plpgsql')"
                )
                row = cur.fetchone()
                if row and any(int(count or 0) > 0 for count in row):
                    raise RuntimeError("refusing to restore into non-empty target database")
    except Exception as exc:
        if "refusing to restore into non-empty" in str(exc):
            raise
        raise RuntimeError(f"failed to check target database empty state: {exc}") from None


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


def _validate_blob_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Validate all members in blobs.tar. Refuses path traversal, symlinks, absolute paths, devices, duplicates."""
    validated: list[tarfile.TarInfo] = []
    seen_dest_paths = set()
    for member in tar.getmembers():
        name = member.name
        if any(c in name for c in ("\r", "\n", "\0", "\\")):
            raise RuntimeError(f"unsafe member path in blobs.tar: invalid characters in {name!r}")
        if member.issym() or member.islnk() or member.isdev() or member.ischr() or member.isfifo():
            raise RuntimeError(f"unsafe member type in blobs.tar: {member.type} ({name!r})")
        if name.startswith("/") or name.startswith("\\"):
            raise RuntimeError(f"unsafe absolute path in blobs.tar: {name!r}")
        if ":" in name.split("/")[0]:
            raise RuntimeError(f"unsafe drive specification in blobs.tar: {name!r}")

        parts = [p for p in name.split("/") if p != ""]
        if any(p in ("..", ".") for p in parts):
            raise RuntimeError(f"path traversal detected in blobs.tar member: {name!r}")

        if member.isdir():
            if not name.startswith("blobs"):
                raise RuntimeError(f"disallowed directory in blobs.tar: {name!r}")
            validated.append(member)
            continue

        if not member.isfile():
            raise RuntimeError(f"only regular files allowed in blobs.tar: {name!r}")

        if not name.startswith("blobs/"):
            raise RuntimeError(f"member does not start with blobs/ in blobs.tar: {name!r}")

        rel_path = name[len("blobs/") :].strip("/")
        if not rel_path or "//" in name:
            raise RuntimeError(f"invalid empty or double-slash member path: {name!r}")

        if rel_path in seen_dest_paths:
            raise RuntimeError(f"duplicate member path in blobs.tar: {name!r}")
        seen_dest_paths.add(rel_path)
        validated.append(member)
    return validated


def _resolve_restore_target(target_blobs_dir: str | Path) -> Path:
    """Resolve a restore target blobs dir (traversal/symlink guards only)."""
    raw_path = Path(target_blobs_dir)
    if any(part in ("..", ".") for part in raw_path.parts):
        raise RuntimeError(f"path traversal detected in target blobs dir: {target_blobs_dir}")
    if raw_path.is_symlink():
        raise RuntimeError(f"refusing target blobs dir as symlink: {target_blobs_dir}")
    resolved = raw_path.resolve()
    if resolved.is_symlink():
        raise RuntimeError(f"refusing resolved target blobs dir as symlink: {resolved}")
    if resolved.exists() and not resolved.is_dir():
        raise RuntimeError(f"target blobs destination is not a directory: {resolved}")
    return resolved


def _validate_restore_destination(target_blobs_dir: str | Path) -> Path:
    resolved = _resolve_restore_target(target_blobs_dir)
    if resolved.exists():
        try:
            if any(resolved.iterdir()):
                raise RuntimeError(f"refusing to restore into non-empty target blobs dir: {resolved}")
        except PermissionError:
            raise RuntimeError(f"permission denied accessing target blobs dir: {resolved}")
    return resolved


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


def _copy_restore_package_snapshot(source_dir: Path, snapshot_dir: Path) -> None:
    """Copy only package members into the private directory used for verify and restore."""
    _make_private_dir(snapshot_dir)
    names = (
        "backup.kkbak",
        _MANIFEST_FILENAME,
        _MANIFEST_CHECKSUM_FILENAME,
        *_PLAIN_MEMBER_ALLOWLIST,
    )
    for name in names:
        source = source_dir / name
        if source.is_symlink():
            raise RuntimeError(f"refusing symlink in restore package: {name}")
        if source.is_file():
            target = snapshot_dir / name
            shutil.copyfile(source, target)
            _set_private_file(target)


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
        dump_timeout = _timeout_from_env("MAIL_CORE_PG_DUMP_TIMEOUT")
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
                raise PgDumpError(f"pg_dump timed out after {dump_timeout}s") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode(errors="replace")[:500] if exc.stderr else str(exc)
            log.warning("pg_dump failed: %s", detail)
            if not allow_stub:
                raise PgDumpError(f"pg_dump failed: {detail}") from exc
    elif not allow_stub:
        raise PgDumpError("pg_dump binary not found on PATH")
    dest.write_text(
        "-- mail-core backup stub: pg_dump unavailable or failed\n"
        f"-- url={_redact_url(url)}\n"
        f"-- at={datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    return _SQL_STUB_METHOD


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
        blob_root=_MANIFEST_BLOB_LOGICAL_NAME,
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
    """Write an encrypted backup unless plaintext is explicitly requested.

    ``allow_dump_stub`` is for offline unit/crypto drills only. Production callers
    must leave it false so a failed pg_dump cannot seal as a successful backup.
    """
    out = Path(output_dir)
    if out.is_symlink():
        raise RuntimeError(f"refusing to use symlink as output directory: {out}")
    url = database_url_override or database_url()
    root = blobs_dir or blob_root()
    do_encrypt = True if encrypt is None else encrypt

    if not do_encrypt:
        out.parent.mkdir(parents=True, exist_ok=True)
        plain_stage = out.parent / f".staging_plain_{out.name}_{uuid.uuid4().hex}"
        if plain_stage.is_symlink():
            raise RuntimeError(f"refusing plain staging dir as symlink: {plain_stage}")
        _make_private_dir(plain_stage)
        try:
            manifest = _build_plain_dir(
                plain_stage,
                url=url,
                root=root,
                include_blobs=include_blobs,
                allow_dump_stub=allow_dump_stub,
            )
            man_path = plain_stage / _MANIFEST_FILENAME
            man_path.write_text(
                json.dumps(asdict(manifest), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            _set_private_file(man_path)
            sha_path = plain_stage / _MANIFEST_CHECKSUM_FILENAME
            sha_path.write_text(
                f"{_sha256_file(man_path)}  {_MANIFEST_FILENAME}\n",
                encoding="utf-8",
            )
            _set_private_file(sha_path)

            old_dir = out.parent / f".old_{out.name}_{uuid.uuid4().hex}"
            if out.exists():
                if out.is_symlink():
                    raise RuntimeError(f"refusing existing destination as symlink: {out}")
                out.rename(old_dir)
            try:
                plain_stage.rename(out)
                if old_dir.exists():
                    _safe_rmtree(old_dir)
            except Exception:
                if old_dir.exists():
                    old_dir.rename(out)
                raise
            log.info("backup package written to %s (plaintext)", out)
            return out
        finally:
            _safe_rmtree(plain_stage)

    key, version = load_backup_key()
    _ensure_backup_key_separate_from_blobs(key)
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
    if not isinstance(members, dict):
        errors.append(f"manifest members must be an object, got {type(members).__name__}")
        return 0
    checked = 0
    for name, meta in members.items():
        if not isinstance(name, str):
            errors.append(f"invalid member name: {name!r}")
            continue
        if name.startswith("plain/") or name == "backup.kkbak":
            # Outer sealed aliases — handled separately before decrypt.
            continue
        if _safe_member_relpath(name, allowlist=_PLAIN_MEMBER_ALLOWLIST) is None:
            errors.append(f"disallowed member name: {name!r}")
            continue
        if not isinstance(meta, dict):
            errors.append(f"invalid member metadata for {name}: expected object")
            continue
        path = _resolve_member_file(work, name)
        if path is None or not path.is_file():
            errors.append(f"missing member {name}")
            continue
        method = meta.get("method")
        if method == _SQL_STUB_METHOD and not allow_stub:
            errors.append(
                f"{name} is {_SQL_STUB_METHOD} (pg_dump failed or skipped); backup is not restoreable"
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
        if not isinstance(outer, dict):
            return RestoreVerifyResult(
                ok=False,
                members_checked=0,
                errors=errors + [f"outer {_MANIFEST_FILENAME} is not an object"],
            )
        outer_members = outer.get("members") or {}
        if not isinstance(outer_members, dict):
            return RestoreVerifyResult(
                ok=False,
                members_checked=0,
                errors=errors + ["outer manifest members must be an object"],
            )
        meta = outer_members.get("backup.kkbak") or {}
        if not isinstance(meta, dict):
            return RestoreVerifyResult(
                ok=False,
                members_checked=0,
                errors=errors + ["outer manifest backup.kkbak metadata must be an object"],
            )
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
    if not isinstance(manifest, dict):
        return RestoreVerifyResult(
            ok=False,
            members_checked=checked,
            errors=errors + [f"{_MANIFEST_FILENAME} is not an object"],
            backup_key_version=key_version,
        )
    _verify_manifest_file_checksum(
        man_path, work / _MANIFEST_CHECKSUM_FILENAME, errors
    )
    members = manifest.get("members") or {}
    if not isinstance(members, dict):
        errors.append("manifest members must be an object")
        return RestoreVerifyResult(
            ok=False,
            members_checked=checked,
            errors=errors,
            backup_key_version=key_version,
        )
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
    with _backup_destination_lock(dest):
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
            try:
                from datetime import datetime, timezone
                import json
                from mail_core.db.session import get_session_factory
                from mail_core.mail.storage.models import AppSetting

                Session = get_session_factory()
                with Session() as session:
                    val = json.dumps(
                        {"finished_at": datetime.now(timezone.utc).isoformat(), "status": "ok"},
                        sort_keys=True,
                    )
                    row = session.get(AppSetting, "backup:last_success")
                    if row is None:
                        session.add(AppSetting(key="backup:last_success", value=val))
                    else:
                        row.value = val
                    session.commit()
            except Exception as exc:
                log.warning("failed to record backup:last_success: %s", exc)

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

# ---------------------------------------------------------------------------
# Cross-volume-safe restore (R12, repair design section 8).
#
# Sequencing is "publish blobs fully, THEN commit the database":
#   1. verify the backup's private snapshot, target DB identity, emptiness;
#      take the restore operation's exclusive lock;
#   2. stage blobs INSIDE the target blob root (same filesystem as the
#      final files), validating every tar member before extracting;
#   3. publish staging contents item-by-item into the target's standard
#      paths (renames only ever inside the target root), then mark the
#      operation log ``blobs_published`` (atomic write + fsync);
#   4. ``pg_restore --single-transaction --exit-on-error`` — when the DB
#      commits, every blob is already in place; there is no post-commit
#      cross-volume publish step anymore;
#   5. verify schema / business associations / blob decryption samples and
#      only then mark the operation ``complete``.
#
# Preconditions (unchanged): the restore target is exclusive, the target
# database and blob root must be empty, and the application and worker
# must be stopped for the duration of the restore.
#
# The operation log records ONLY: operation_id, package digest, canonical
# target paths, DB cluster/database identity, and stage. Never passwords
# or keys.
# ---------------------------------------------------------------------------

_RESTORE_OPERATION_LOG_FILENAME = ".restore_operation.json"
_RESTORE_STAGING_PREFIX = ".restore_staging_"
_RESTORE_OPERATION_LOG_KEYS = (
    "operation_id",
    "package_digest",
    "target_paths",
    "database_identity",
    "stage",
)
# Restore operation stages, and what each proves about the DB commit:
#   staging           written before blobs are published and before the DB
#                     step runs at all — no commit can have happened.
#   db_failed         written only after pg_restore returned a definitive
#                     failure; pg_restore runs --single-transaction, so a
#                     failed attempt rolled back — no commit happened.
#   blobs_published   blobs are in the target but the DB step's outcome is
#                     not recorded; a crash here leaves the commit outcome
#                     unknown (the fresh-restore path upgrades a log stuck
#                     at this stage to needs_verification for that reason).
#   needs_verification  the commit outcome is explicitly unknown.
#   complete          the DB committed and verification passed; the blobs
#                     are the live restored data.
# Cleanup may delete an operation's files only from a stage that proves
# the commit did NOT happen, so only staging / db_failed are eligible.
_CLEANUP_ELIGIBLE_RESTORE_STAGES = frozenset({"staging", "db_failed"})

_RESTORE_REQUIRED_TABLES = frozenset(
    {"accounts", "messages", "message_bodies", "message_blobs", "message_blob_links", "attachments"}
)


class RestoreCommitUncertainError(RuntimeError):
    """pg_restore may or may not have committed (e.g. it timed out)."""


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _restore_operation_log_path(target_blobs: Path) -> Path:
    return target_blobs / _RESTORE_OPERATION_LOG_FILENAME


def _restore_staging_dir(target_blobs: Path, operation_id: str) -> Path:
    return target_blobs / f"{_RESTORE_STAGING_PREFIX}{operation_id}"


def _validate_operation_id(operation_id: str) -> str:
    if (
        not operation_id
        or len(operation_id) > 64
        or any(not (c.isalnum() or c in "-_") for c in operation_id)
    ):
        raise RuntimeError(f"invalid restore operation_id: {operation_id!r}")
    return operation_id


def _operation_log_payload(
    *,
    operation_id: str,
    package_digest: str,
    target_blobs: Path,
    target_database_url: str,
    target_ident: DatabaseIdentity | None,
    stage: str,
) -> dict:
    scheme, host, port, database_name = _restore_database_identity(target_database_url)
    return {
        "operation_id": operation_id,
        "package_digest": package_digest,
        "target_paths": {"blobs_dir": str(target_blobs)},
        "database_identity": {
            "scheme": scheme,
            "host": host,
            "port": port,
            "database_name": database_name,
            "system_identifier": target_ident.system_identifier if target_ident else None,
            "database_oid": target_ident.database_oid if target_ident else None,
        },
        "stage": stage,
    }


def _write_restore_operation_log(target_blobs: Path, payload: dict, *, stage: str) -> dict:
    """Atomically write the operation log (temp file + rename + fsync).

    Temp file, log file and target live in the same directory, so the
    rename can never cross a filesystem boundary.
    """
    data = {key: payload[key] for key in _RESTORE_OPERATION_LOG_KEYS}
    data["stage"] = stage
    tmp = target_blobs / f"{_RESTORE_OPERATION_LOG_FILENAME}.tmp-{uuid.uuid4().hex}"
    with tmp.open("xb") as fh:
        fh.write((json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())
    _set_private_file(tmp)
    tmp.replace(_restore_operation_log_path(target_blobs))
    _fsync_dir(target_blobs)
    return data


def _read_restore_operation_log(target_blobs: Path) -> dict | None:
    path = _restore_operation_log_path(target_blobs)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"restore operation log is corrupt: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("operation_id"), str):
        raise RuntimeError(f"restore operation log is corrupt: {path}")
    return data


def _assert_operation_log_matches(
    op_log: dict,
    *,
    operation_id: str,
    target_blobs: Path,
    target_database_url: str | None = None,
    target_ident: DatabaseIdentity | None = None,
) -> None:
    """Ownership/identity verification shared by resume, verify and cleanup."""
    if op_log.get("operation_id") != operation_id:
        raise RuntimeError(
            "restore operation id mismatch: target belongs to operation "
            f"{op_log.get('operation_id')!r}, not {operation_id!r}"
        )
    logged_target = (op_log.get("target_paths") or {}).get("blobs_dir")
    if logged_target != str(target_blobs):
        raise RuntimeError(
            "restore operation target path mismatch: log records "
            f"{logged_target!r}, not {str(target_blobs)!r}"
        )
    if target_database_url is None:
        return
    scheme, host, port, database_name = _restore_database_identity(target_database_url)
    identity = op_log.get("database_identity") or {}
    nominal = {
        "scheme": scheme,
        "host": host,
        "port": port,
        "database_name": database_name,
    }
    for key, current in nominal.items():
        if identity.get(key) is not None and identity.get(key) != current:
            raise RuntimeError(
                "restore operation database identity mismatch: "
                f"{key} is {identity.get(key)!r} in the operation log, not {current!r}"
            )
    if target_ident is not None:
        for key, current in (
            ("system_identifier", target_ident.system_identifier),
            ("database_oid", target_ident.database_oid),
        ):
            logged = identity.get(key)
            if logged is not None and current is not None and logged != current:
                raise RuntimeError(
                    "restore operation database identity mismatch: "
                    f"cluster {key} is {logged!r} in the operation log, not {current!r}"
                )


def _package_snapshot_digest(snapshot_dir: Path) -> str:
    """Digest of the verified private package snapshot (names + file hashes)."""
    h = hashlib.sha256()
    for path in sorted(
        (p for p in snapshot_dir.iterdir() if p.is_file()), key=lambda p: p.name
    ):
        h.update(path.name.encode("utf-8"))
        h.update(b"\0")
        h.update(_sha256_file(path).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class _PreparedRestorePackage:
    manifest: dict
    package_size: int
    package_digest: str
    dump_file: Path
    blobs_tar: Path | None


def _prepare_restore_package(
    pkg_dir: Path,
    work_dir: Path,
    *,
    keyring: dict[int, bytes] | None,
    allow_stub: bool,
    source_ident: DatabaseIdentity | None,
    target_ident: DatabaseIdentity | None,
    check_source_cluster: bool = True,
) -> _PreparedRestorePackage:
    """Snapshot + verify + decrypt a backup package inside ``work_dir``.

    This only reads the package filesystem; no blob is staged or published
    here, so nothing depends on the package and target sharing a volume.
    """
    errors: list[str] = []
    snapshot_dir = work_dir / "package"
    _make_private_dir(snapshot_dir)
    _copy_restore_package_snapshot(pkg_dir, snapshot_dir)
    pkg_size = sum(f.stat().st_size for f in snapshot_dir.glob("**/*") if f.is_file())
    vr = verify_backup_package(snapshot_dir, allow_stub=allow_stub)
    if not vr.ok:
        raise RuntimeError(f"backup package verification failed: {vr.errors}")
    package_digest = _package_snapshot_digest(snapshot_dir)

    kkbak = snapshot_dir / "backup.kkbak"
    if kkbak.is_file():
        plain_tar = work_dir / "plain.tar"
        keyring_to_use = keyring or load_backup_keyring()
        decrypt_file(kkbak, plain_tar, keyring=keyring_to_use)
        extract_dir = work_dir / "extracted"
        _make_private_dir(extract_dir)
        if not _extract_tar_file(plain_tar, extract_dir, errors):
            raise RuntimeError(f"tar extraction failed: {errors}")
    else:
        # Plain package members come from the same private snapshot that was verified.
        extract_dir = snapshot_dir

    man_path = extract_dir / _MANIFEST_FILENAME
    if not man_path.is_file():
        raise RuntimeError(f"missing {_MANIFEST_FILENAME} in backup archive")
    manifest = json.loads(man_path.read_text(encoding="utf-8"))

    effective_source = source_ident
    manifest_src_ident = manifest.get("source_database_identity")
    if not check_source_cluster:
        effective_source = None
        manifest_src_ident = None
    if effective_source is None and isinstance(manifest_src_ident, dict):
        effective_source = DatabaseIdentity(
            system_identifier=manifest_src_ident.get("system_identifier"),
            database_oid=manifest_src_ident.get("database_oid"),
            database_name=manifest_src_ident.get("database_name", ""),
        )
    if effective_source is not None and target_ident is not None:
        if (
            effective_source.system_identifier is not None
            and target_ident.system_identifier is not None
            and effective_source.system_identifier == target_ident.system_identifier
            and (
                (
                    effective_source.database_oid is not None
                    and effective_source.database_oid == target_ident.database_oid
                )
                or effective_source.database_name == target_ident.database_name
            )
        ):
            raise RuntimeError("refusing to restore onto source database")

    dump_meta = manifest.get("members", {}).get("postgres.dump", {})
    if dump_meta.get("method", "custom") == _SQL_STUB_METHOD and not allow_stub:
        raise RuntimeError("refusing to restore stub backup without allow_stub")

    dump_file = extract_dir / "postgres.dump"
    blobs_tar = extract_dir / "blobs.tar"
    return _PreparedRestorePackage(
        manifest=manifest,
        package_size=pkg_size,
        package_digest=package_digest,
        dump_file=dump_file,
        blobs_tar=blobs_tar if blobs_tar.is_file() else None,
    )


def _blob_tar_inventory(blobs_tar: Path) -> tuple[dict[str, str], list[str]]:
    """Validate ALL tar members, then return {relpath: sha256} and dir relpaths."""
    inventory: dict[str, str] = {}
    dirs: list[str] = []
    with tarfile.open(blobs_tar, "r") as t:
        validated_members = _validate_blob_members(t)
        for member in validated_members:
            if member.isdir():
                rel = (
                    member.name[len("blobs/") :].strip("/")
                    if member.name.startswith("blobs/")
                    else ""
                )
                if rel:
                    dirs.append(rel)
                continue
            rel_path = member.name[len("blobs/") :].strip("/")
            f = t.extractfile(member)
            if f is None:
                raise RuntimeError(f"cannot read blobs.tar member: {member.name!r}")
            h = hashlib.sha256()
            with f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            inventory[rel_path] = h.hexdigest()
    return inventory, dirs


def _extract_blobs_to_staging(
    blobs_tar: Path, staging_blobs: Path
) -> tuple[dict[str, str], list[str]]:
    """Stream-extract blobs.tar into staging (inside the target blob root).

    Every member is validated before the first file is written; each file
    is written to a temp file in its destination directory, fsynced, then
    renamed within that same directory.
    """
    inventory: dict[str, str] = {}
    dirs: list[str] = []
    with tarfile.open(blobs_tar, "r") as t:
        validated_members = _validate_blob_members(t)
        for member in validated_members:
            if member.isdir():
                rel = (
                    member.name[len("blobs/") :].strip("/")
                    if member.name.startswith("blobs/")
                    else ""
                )
                if rel:
                    dirs.append(rel)
                    (staging_blobs / rel).mkdir(parents=True, exist_ok=True)
                continue
            rel_path = member.name[len("blobs/") :].strip("/")
            dest_file = staging_blobs / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            f = t.extractfile(member)
            if f is None:
                raise RuntimeError(f"cannot read blobs.tar member: {member.name!r}")
            temp_file = dest_file.with_name(
                f".{dest_file.name}.restore-{uuid.uuid4().hex}"
            )
            created = False
            streamed = hashlib.sha256()
            try:
                with f, temp_file.open("xb") as out:
                    created = True
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        streamed.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                temp_file.replace(dest_file)
            finally:
                if created:
                    try:
                        temp_file.unlink(missing_ok=True)
                    except OSError:
                        pass
            # The bytes that landed on the target filesystem must be the
            # bytes that were streamed out of the verified tar.
            if _sha256_file(dest_file) != streamed.hexdigest():
                raise RuntimeError(
                    f"extracted blob checksum mismatch for {rel_path}: "
                    "staged file does not match the blobs.tar member"
                )
            inventory[rel_path] = streamed.hexdigest()
    return inventory, dirs


def _publish_rename(src: Path, dst: Path, root: Path) -> None:
    """Rename one staged file to its final path, inside ``root`` only."""
    src_resolved = src.resolve()
    dst_resolved = dst.resolve(strict=False)
    if root not in src_resolved.parents:
        raise RuntimeError(f"refusing publish rename from outside the target root: {src}")
    if root not in dst_resolved.parents:
        raise RuntimeError(f"refusing publish rename to outside the target root: {dst}")
    src.replace(dst)


def _publish_staged_blobs(
    staging_blobs: Path,
    target_blobs: Path,
    inventory: dict[str, str],
    dirs: list[str],
) -> int:
    """Publish staged files item-by-item into the target's standard paths.

    A destination that already holds this operation's identical file
    (partial publish from an earlier attempt of the same operation) is
    kept; any other existing file is refused, never overwritten.
    """
    for rel_dir in dirs:
        (target_blobs / rel_dir).mkdir(parents=True, exist_ok=True)
    for rel_path in sorted(inventory):
        expected = inventory[rel_path]
        dest_file = target_blobs / rel_path
        staged_file = staging_blobs / rel_path
        if dest_file.is_file():
            if _sha256_file(dest_file) != expected:
                raise RuntimeError(
                    f"refusing to overwrite existing blob with a different checksum: {rel_path}"
                )
            if staged_file.is_file():
                staged_file.unlink()
            continue
        if dest_file.exists():
            raise RuntimeError(f"refusing to overwrite existing blob path: {rel_path}")
        if not staged_file.is_file():
            raise RuntimeError(f"staged blob missing before publish: {rel_path}")
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        _publish_rename(staged_file, dest_file, target_blobs)
        _fsync_dir(dest_file.parent)
    _safe_rmtree(staging_blobs)
    _fsync_dir(target_blobs)
    return len(inventory)


def _target_blob_files(target_blobs: Path) -> dict[str, Path]:
    """Regular files in the target root, excluding log and staging areas."""
    found: dict[str, Path] = {}
    if not target_blobs.is_dir():
        return found
    for path in target_blobs.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(target_blobs).as_posix()
        first = rel.split("/", 1)[0]
        if first == _RESTORE_OPERATION_LOG_FILENAME or first.startswith(
            _RESTORE_OPERATION_LOG_FILENAME + ".tmp-"
        ):
            continue
        if first.startswith(_RESTORE_STAGING_PREFIX):
            continue
        found[rel] = path
    return found


def _verify_published_blob_files(target_blobs: Path, inventory: dict[str, str]) -> None:
    """Exact-set + checksum verification of published blobs against the package."""
    actual = _target_blob_files(target_blobs)
    if set(actual) != set(inventory):
        missing = sorted(set(inventory) - set(actual))
        unexpected = sorted(set(actual) - set(inventory))
        raise RuntimeError(
            "published blob file set mismatch with the backup package: "
            f"missing={missing}, unexpected={unexpected}"
        )
    for rel_path, path in actual.items():
        if _sha256_file(path) != inventory[rel_path]:
            raise RuntimeError(f"published blob checksum mismatch: {rel_path}")


def _verify_published_blob_subset(target_blobs: Path, inventory: dict[str, str]) -> None:
    """Every file already published must belong to, and match, the package."""
    for rel_path, path in _target_blob_files(target_blobs).items():
        if rel_path not in inventory:
            raise RuntimeError(
                f"unexpected file in restore target, not from this backup: {rel_path}"
            )
        if _sha256_file(path) != inventory[rel_path]:
            raise RuntimeError(f"published blob checksum mismatch: {rel_path}")


def _database_is_empty(target_database_url: str) -> bool | None:
    """True if provably empty, False if provably non-empty, None if unknown."""
    try:
        _assert_target_database_is_empty(target_database_url)
        return True
    except RuntimeError as exc:
        if "non-empty" in str(exc):
            return False
        return None


def _verify_restored_state(
    target_database_url: str,
    target_blobs: Path,
    inventory: dict[str, str],
    *,
    db_reachable: bool,
) -> None:
    """Post-commit verification: blobs on disk, then (when the DB is
    reachable) schema, business associations and blob decryption samples.

    Raises RuntimeError on any verified failure. When the target DB was
    not reachable at restore start (offline drills), only the local blob
    checks can run and the DB checks are skipped.
    """
    _verify_published_blob_files(target_blobs, inventory)
    if not db_reachable:
        return

    dsn, password = _libpq_dsn_and_password(target_database_url)
    import psycopg

    conn_kwargs = {"autocommit": True, "connect_timeout": 5}
    if password is not None:
        conn_kwargs["password"] = password
    storage_paths: list[str] = []
    try:
        with psycopg.connect(dsn, **conn_kwargs) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('pg_catalog', 'information_schema')"
                )
                tables = {str(row[0]) for row in cur.fetchall()}
                missing_tables = sorted(_RESTORE_REQUIRED_TABLES - tables)
                if missing_tables:
                    raise RuntimeError(
                        "restored database schema verification failed: "
                        f"missing tables {missing_tables}"
                    )
                orphan_queries = {
                    "message_blob_links without message_blobs": (
                        "SELECT count(*) FROM message_blob_links l "
                        "LEFT JOIN message_blobs b ON b.id = l.blob_id WHERE b.id IS NULL"
                    ),
                    "attachments without message_blobs": (
                        "SELECT count(*) FROM attachments a "
                        "LEFT JOIN message_blobs b ON b.id = a.blob_id "
                        "WHERE a.blob_id IS NOT NULL AND b.id IS NULL"
                    ),
                    "message_bodies without messages": (
                        "SELECT count(*) FROM message_bodies mb "
                        "LEFT JOIN messages m ON m.id = mb.message_id WHERE m.id IS NULL"
                    ),
                }
                for label, query in orphan_queries.items():
                    cur.execute(query)
                    row = cur.fetchone()
                    if row and row[0] > 0:
                        raise RuntimeError(
                            "restored database business association verification "
                            f"failed: {row[0]} rows of {label}"
                        )
                cur.execute(
                    "SELECT storage_path FROM message_blobs "
                    "WHERE storage_path IS NOT NULL LIMIT 50"
                )
                storage_paths = [str(row[0]) for row in cur.fetchall()]
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"restored database verification failed: {exc}") from exc

    samples: list[Path] = []
    for storage_path in storage_paths:
        path = target_blobs / storage_path
        if not path.is_file():
            raise RuntimeError(
                f"restored blob referenced by the database is missing: {storage_path}"
            )
        with path.open("rb") as fh:
            if fh.read(len(_BLOB_MAGIC)) == _BLOB_MAGIC and len(samples) < 3:
                samples.append(path)
    if samples:
        try:
            keyring = load_keyring_from_env()
        except BlobCryptoError as exc:
            raise RuntimeError(
                f"blob decryption sample verification failed: {exc}"
            ) from exc
        for path in samples:
            try:
                with path.open("rb") as fh:
                    plaintext = b"".join(iter_unwrap(fh, keyring=keyring))
            except BlobCryptoError as exc:
                raise RuntimeError(
                    f"blob decryption sample verification failed for "
                    f"{path.relative_to(target_blobs)}: {exc}"
                ) from exc
            stem = path.name.removesuffix(".blob")
            if len(stem) == 64 and all(c in "0123456789abcdef" for c in stem):
                if hashlib.sha256(plaintext).hexdigest() != stem:
                    raise RuntimeError(
                        "blob decryption sample verification failed: plaintext "
                        f"digest mismatch for {path.relative_to(target_blobs)}"
                    )


def _run_pg_restore(dump_file: Path, target_database_url: str) -> None:
    """Run the single-transaction restore. Definite failure -> RuntimeError;
    an outcome that cannot be known (timeout) -> RestoreCommitUncertainError."""
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
    restore_timeout = _timeout_from_env("MAIL_CORE_PG_RESTORE_TIMEOUT")
    cmd = [
        pg_restore,
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        dsn,
        str(dump_file),
    ]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            env=env,
            timeout=restore_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RestoreCommitUncertainError(
            f"pg_restore timed out after {restore_timeout}s; its commit outcome is unknown"
        ) from exc
    if res.returncode != 0:
        err_msg = (res.stderr or b"").decode("utf-8", errors="replace").strip()[:1000]
        if not err_msg:
            err_msg = "(no stderr output)"
        log.warning("pg_restore returned code %d: %s", res.returncode, err_msg)
        raise RuntimeError(f"pg_restore failed ({res.returncode}): {err_msg}")


def _execute_db_step(
    *,
    target_blobs: Path,
    log_payload: dict,
    dump_file: Path,
    target_database_url: str,
    target_ident: DatabaseIdentity | None,
    begun: datetime,
    package_size: int,
    blobs_restored: int,
    inventory: dict[str, str],
) -> RestoreResult:
    """Steps 4-5: commit the DB (blobs are already published), verify, complete."""
    operation_id = log_payload["operation_id"]
    try:
        _run_pg_restore(dump_file, target_database_url)
    except RestoreCommitUncertainError as exc:
        _write_restore_operation_log(target_blobs, log_payload, stage="needs_verification")
        raise RuntimeError(
            f"restore operation {operation_id} entered needs_verification: {exc}"
        ) from exc
    except RuntimeError:
        _write_restore_operation_log(target_blobs, log_payload, stage="db_failed")
        raise
    try:
        _verify_restored_state(
            target_database_url,
            target_blobs,
            inventory,
            db_reachable=target_ident is not None,
        )
    except Exception as exc:
        _write_restore_operation_log(target_blobs, log_payload, stage="needs_verification")
        raise RuntimeError(
            f"restore operation {operation_id} entered needs_verification: "
            f"post-restore verification did not complete: {exc}"
        ) from exc
    _write_restore_operation_log(target_blobs, log_payload, stage="complete")
    duration = (datetime.now(timezone.utc) - begun).total_seconds()
    return RestoreResult(
        ok=True,
        database_restored=True,
        blobs_restored=blobs_restored,
        duration_seconds=duration,
        package_size_bytes=package_size,
        errors=[],
        operation_id=operation_id,
        stage="complete",
    )


def _read_target_identity(target_database_url: str) -> DatabaseIdentity | None:
    try:
        return _read_database_identity(target_database_url)
    except Exception:
        return None


def _resolve_package_dir(package_path: str | Path) -> Path:
    pkg = Path(package_path).resolve()
    if pkg.is_dir():
        return pkg
    if pkg.is_file():
        return pkg.parent
    raise FileNotFoundError(f"backup package not found: {pkg}")


@dataclass(frozen=True, slots=True)
class RestoreResult:
    ok: bool
    database_restored: bool
    blobs_restored: int
    duration_seconds: float
    package_size_bytes: int
    errors: list[str]
    operation_id: str = ""
    stage: str = ""


def restore_backup_package(
    package_path: str | Path,
    *,
    target_database_url: str,
    target_blobs_dir: str | Path,
    keyring: dict[int, bytes] | None = None,
    allow_stub: bool = False,
    source_database_url: str,
    operation_id: str | None = None,
) -> RestoreResult:
    """Restore a backup package into an empty target database and blob root.

    Cross-volume-safe sequencing (repair design section 8): blobs are
    staged inside the target blob root, published in full, and only then
    is the database committed with ``pg_restore --single-transaction``.

    Preconditions: the target is exclusive to this operation, the target
    database and blob root are empty, and the application and worker are
    stopped for the duration of the restore. A target that already
    belongs to an earlier restore operation is never replayed, wiped or
    overwritten here — use :func:`resume_restore_backup_package`,
    :func:`verify_restore_operation` or :func:`cleanup_restore_operation`.
    """
    begun = datetime.now(timezone.utc)
    pkg_dir = _resolve_package_dir(package_path)

    # Guard AC-004: Prevent restoring onto the same source database.
    if _restore_database_identity(source_database_url) == _restore_database_identity(
        target_database_url
    ):
        raise RuntimeError("refusing to restore onto source database")

    target_ident = _read_target_identity(target_database_url)
    source_ident = _read_target_identity(source_database_url)
    if source_ident is not None and target_ident is not None:
        if (
            source_ident.system_identifier is not None
            and target_ident.system_identifier is not None
            and source_ident.system_identifier == target_ident.system_identifier
            and (
                (
                    source_ident.database_oid is not None
                    and source_ident.database_oid == target_ident.database_oid
                )
                or source_ident.database_name == target_ident.database_name
            )
        ):
            raise RuntimeError("refusing to restore onto source database")

    # Enforce empty target database before restore if accessible
    if target_ident is not None:
        _assert_target_database_is_empty(target_database_url)

    target_blobs = _resolve_restore_target(target_blobs_dir)

    # A target owned by an earlier operation is never auto-replayed or
    # auto-deleted. A log stuck at blobs_published means the DB commit
    # outcome is unknown, so the operation first enters needs_verification.
    if target_blobs.is_dir():
        existing_log = _read_restore_operation_log(target_blobs)
        if existing_log is not None:
            existing_stage = str(existing_log.get("stage") or "")
            if existing_stage == "blobs_published":
                _write_restore_operation_log(
                    target_blobs, existing_log, stage="needs_verification"
                )
                existing_stage = "needs_verification"
            raise RuntimeError(
                "refusing fresh restore: target already belongs to restore "
                f"operation {existing_log.get('operation_id')} (stage "
                f"{existing_stage}); use resume, verification or cleanup "
                "for that operation instead"
            )

    target_blobs = _validate_restore_destination(target_blobs_dir)
    op_id = _validate_operation_id(operation_id or uuid.uuid4().hex)

    target_blobs.parent.mkdir(parents=True, exist_ok=True)
    target_blobs.mkdir(parents=True, exist_ok=True)

    # Exclusive restore target: one operation at a time per blob root.
    with _backup_destination_lock(target_blobs):
        if _read_restore_operation_log(target_blobs) is not None:
            raise RuntimeError(
                "refusing fresh restore: a restore operation log appeared "
                "in the target while acquiring the exclusive lock"
            )
        work_dir = pkg_dir.parent / f".restore_work_{uuid.uuid4().hex}"
        _make_private_dir(work_dir)
        try:
            prepared = _prepare_restore_package(
                pkg_dir,
                work_dir,
                keyring=keyring,
                allow_stub=allow_stub,
                source_ident=source_ident,
                target_ident=target_ident,
            )
            log_payload = _operation_log_payload(
                operation_id=op_id,
                package_digest=prepared.package_digest,
                target_blobs=target_blobs,
                target_database_url=target_database_url,
                target_ident=target_ident,
                stage="staging",
            )
            _write_restore_operation_log(target_blobs, log_payload, stage="staging")

            # Stage blobs INSIDE the target root (same filesystem as the
            # final files), then publish them fully — before any DB work.
            inventory: dict[str, str] = {}
            if prepared.blobs_tar is not None:
                staging_blobs = _restore_staging_dir(target_blobs, op_id)
                _make_private_dir(staging_blobs)
                inventory, dirs = _extract_blobs_to_staging(
                    prepared.blobs_tar, staging_blobs
                )
                _publish_staged_blobs(staging_blobs, target_blobs, inventory, dirs)
            _write_restore_operation_log(
                target_blobs, log_payload, stage="blobs_published"
            )

            return _execute_db_step(
                target_blobs=target_blobs,
                log_payload=log_payload,
                dump_file=prepared.dump_file,
                target_database_url=target_database_url,
                target_ident=target_ident,
                begun=begun,
                package_size=prepared.package_size,
                blobs_restored=len(inventory),
                inventory=inventory,
            )
        finally:
            _safe_rmtree(work_dir)


def resume_restore_backup_package(
    package_path: str | Path,
    *,
    operation_id: str,
    target_database_url: str,
    target_blobs_dir: str | Path,
    keyring: dict[int, bytes] | None = None,
    allow_stub: bool = False,
    source_database_url: str,
) -> RestoreResult:
    """Resume an earlier restore operation without overwriting anything.

    The operation's published files are reused ONLY when the operation
    id, target paths, database identity, package digest and every
    published file checksum match the operation log and the package.
    A ``needs_verification`` operation is never auto-replayed.
    """
    begun = datetime.now(timezone.utc)
    pkg_dir = _resolve_package_dir(package_path)
    if _restore_database_identity(source_database_url) == _restore_database_identity(
        target_database_url
    ):
        raise RuntimeError("refusing to restore onto source database")
    op_id = _validate_operation_id(operation_id)

    target_blobs = _resolve_restore_target(target_blobs_dir)
    if not target_blobs.is_dir():
        raise RuntimeError(
            "restore resume refused: target blobs dir does not exist: "
            f"{target_blobs}"
        )
    op_log = _read_restore_operation_log(target_blobs)
    if op_log is None:
        raise RuntimeError(
            "restore resume refused: no restore operation log in target: "
            f"{target_blobs}"
        )
    target_ident = _read_target_identity(target_database_url)
    _assert_operation_log_matches(
        op_log,
        operation_id=op_id,
        target_blobs=target_blobs,
        target_database_url=target_database_url,
        target_ident=target_ident,
    )
    stage = str(op_log.get("stage") or "")
    if stage == "needs_verification":
        raise RuntimeError(
            f"restore operation {op_id} is in needs_verification; explicit "
            "verification is required before any replay, and the database "
            "must not be auto-deleted or auto-restored"
        )

    source_ident = _read_target_identity(source_database_url)
    with _backup_destination_lock(target_blobs):
        # Re-read and re-verify the operation log under the destination
        # lock: the stage that drives the resume must be the stage in
        # effect while the lock is held, not a stale pre-lock snapshot —
        # another restore may have completed this operation while resume
        # waited for the lock, and replaying from the stale stage would
        # regress it (complete -> staging -> db_failed) and expose the
        # published blobs to cleanup. Mirrors cleanup_restore_operation.
        op_log = _read_restore_operation_log(target_blobs)
        if op_log is None:
            raise RuntimeError(
                "restore resume refused: no restore operation log in "
                f"target: {target_blobs}"
            )
        _assert_operation_log_matches(
            op_log,
            operation_id=op_id,
            target_blobs=target_blobs,
            target_database_url=target_database_url,
            target_ident=target_ident,
        )
        stage = str(op_log.get("stage") or "")
        if stage == "needs_verification":
            raise RuntimeError(
                f"restore operation {op_id} is in needs_verification; "
                "explicit verification is required before any replay, and "
                "the database must not be auto-deleted or auto-restored"
            )
        work_dir = pkg_dir.parent / f".restore_work_{uuid.uuid4().hex}"
        _make_private_dir(work_dir)
        try:
            prepared = _prepare_restore_package(
                pkg_dir,
                work_dir,
                keyring=keyring,
                allow_stub=allow_stub,
                source_ident=source_ident,
                target_ident=target_ident,
                check_source_cluster=False,
            )
            if prepared.package_digest != op_log.get("package_digest"):
                raise RuntimeError(
                    "restore resume refused: package digest mismatch with "
                    "the restore operation log"
                )
            inventory: dict[str, str] = {}
            dirs: list[str] = []
            if prepared.blobs_tar is not None:
                inventory, dirs = _blob_tar_inventory(prepared.blobs_tar)
            log_payload = _operation_log_payload(
                operation_id=op_id,
                package_digest=prepared.package_digest,
                target_blobs=target_blobs,
                target_database_url=target_database_url,
                target_ident=target_ident,
                stage=stage,
            )

            if stage == "complete":
                _verify_published_blob_files(target_blobs, inventory)
                return RestoreResult(
                    ok=True,
                    database_restored=True,
                    blobs_restored=len(inventory),
                    duration_seconds=(
                        datetime.now(timezone.utc) - begun
                    ).total_seconds(),
                    package_size_bytes=prepared.package_size,
                    errors=[],
                    operation_id=op_id,
                    stage="complete",
                )

            if stage == "staging":
                # Only this operation's own partial publish may be present;
                # staging itself is private and is rebuilt from the package.
                _verify_published_blob_subset(target_blobs, inventory)
                _write_restore_operation_log(
                    target_blobs, log_payload, stage="staging"
                )
                staging_blobs = _restore_staging_dir(target_blobs, op_id)
                _safe_rmtree(staging_blobs)
                if prepared.blobs_tar is not None:
                    _make_private_dir(staging_blobs)
                    inventory, dirs = _extract_blobs_to_staging(
                        prepared.blobs_tar, staging_blobs
                    )
                    _publish_staged_blobs(
                        staging_blobs, target_blobs, inventory, dirs
                    )
                _write_restore_operation_log(
                    target_blobs, log_payload, stage="blobs_published"
                )
            elif stage in ("blobs_published", "db_failed"):
                _verify_published_blob_files(target_blobs, inventory)
                if target_ident is not None:
                    empty = _database_is_empty(target_database_url)
                    if empty is not True:
                        # Fail closed on ANY non-proof of emptiness: a
                        # provably non-empty DB may hold the earlier
                        # commit, and an undeterminable state (None) is
                        # just as unsafe to replay into — same treatment
                        # as verify_restore_operation's None handling.
                        _write_restore_operation_log(
                            target_blobs, log_payload, stage="needs_verification"
                        )
                        if empty is False:
                            raise RuntimeError(
                                f"restore operation {op_id} entered "
                                "needs_verification: target database is not "
                                "empty, so the earlier pg_restore may have "
                                "committed; refusing to auto-replay the restore"
                            )
                        raise RuntimeError(
                            f"restore operation {op_id} entered "
                            "needs_verification: target database empty "
                            "state could not be determined, so the earlier "
                            "pg_restore outcome is unknown; refusing to "
                            "auto-replay the restore"
                        )
            else:
                raise RuntimeError(
                    f"restore resume refused: unknown operation stage {stage!r}"
                )

            return _execute_db_step(
                target_blobs=target_blobs,
                log_payload=log_payload,
                dump_file=prepared.dump_file,
                target_database_url=target_database_url,
                target_ident=target_ident,
                begun=begun,
                package_size=prepared.package_size,
                blobs_restored=len(inventory),
                inventory=inventory,
            )
        finally:
            _safe_rmtree(work_dir)


def verify_restore_operation(
    package_path: str | Path,
    *,
    operation_id: str,
    target_database_url: str,
    target_blobs_dir: str | Path,
    keyring: dict[int, bytes] | None = None,
    allow_stub: bool = False,
    source_database_url: str,
) -> RestoreResult:
    """Explicitly verify a ``needs_verification`` restore operation.

    A ``complete`` operation is re-validated against the supplied package
    (package digest plus the published file set and checksums) before it
    is reported ok. If the database is verified still empty, the operation returns to
    ``blobs_published`` and a retry via resume is allowed (result
    ``ok=False``). If the database is non-empty, schema, business
    associations, published-file checksums and blob decryption samples
    are verified before the operation is marked ``complete``. Nothing is
    replayed and nothing is deleted here.
    """
    begun = datetime.now(timezone.utc)
    pkg_dir = _resolve_package_dir(package_path)
    if _restore_database_identity(source_database_url) == _restore_database_identity(
        target_database_url
    ):
        raise RuntimeError("refusing to restore onto source database")
    op_id = _validate_operation_id(operation_id)

    target_blobs = _resolve_restore_target(target_blobs_dir)
    op_log = (
        _read_restore_operation_log(target_blobs) if target_blobs.is_dir() else None
    )
    if op_log is None:
        raise RuntimeError(
            "restore verification refused: no restore operation log in "
            f"target: {target_blobs}"
        )
    target_ident = _read_target_identity(target_database_url)
    _assert_operation_log_matches(
        op_log,
        operation_id=op_id,
        target_blobs=target_blobs,
        target_database_url=target_database_url,
        target_ident=target_ident,
    )
    stage = str(op_log.get("stage") or "")
    if stage not in ("complete", "needs_verification"):
        raise RuntimeError(
            f"restore operation {op_id} is in stage {stage!r}, not "
            "needs_verification; use resume for that stage"
        )

    source_ident = _read_target_identity(source_database_url)
    with _backup_destination_lock(target_blobs):
        # Re-read and re-verify the operation log under the destination
        # lock: the stage that drives verification must be the stage in
        # effect while the lock is held, not a stale pre-lock snapshot —
        # another resume/verify may have completed this operation while
        # this call waited for the lock, and writing state back from the
        # stale stage would regress it (complete -> blobs_published).
        # Mirrors resume_restore_backup_package / cleanup_restore_operation.
        op_log = (
            _read_restore_operation_log(target_blobs)
            if target_blobs.is_dir()
            else None
        )
        if op_log is None:
            raise RuntimeError(
                "restore verification refused: no restore operation log in "
                f"target: {target_blobs}"
            )
        _assert_operation_log_matches(
            op_log,
            operation_id=op_id,
            target_blobs=target_blobs,
            target_database_url=target_database_url,
            target_ident=target_ident,
        )
        stage = str(op_log.get("stage") or "")
        if stage not in ("complete", "needs_verification"):
            raise RuntimeError(
                f"restore operation {op_id} is in stage {stage!r}, not "
                "needs_verification; use resume for that stage"
            )
        work_dir = pkg_dir.parent / f".restore_work_{uuid.uuid4().hex}"
        _make_private_dir(work_dir)
        try:
            prepared = _prepare_restore_package(
                pkg_dir,
                work_dir,
                keyring=keyring,
                allow_stub=allow_stub,
                source_ident=source_ident,
                target_ident=target_ident,
                check_source_cluster=False,
            )
            if prepared.package_digest != op_log.get("package_digest"):
                raise RuntimeError(
                    "restore verification refused: package digest mismatch "
                    "with the restore operation log"
                )
            inventory: dict[str, str] = {}
            if prepared.blobs_tar is not None:
                inventory, _dirs = _blob_tar_inventory(prepared.blobs_tar)
            _verify_published_blob_files(target_blobs, inventory)

            if stage == "complete":
                # A completed operation is only "verified" once the
                # package digest and every published file's checksum have
                # been re-checked against the supplied package (above);
                # returning ok without that would let any package claim
                # a completed restore it never produced.
                return RestoreResult(
                    ok=True,
                    database_restored=True,
                    blobs_restored=len(inventory),
                    duration_seconds=(
                        datetime.now(timezone.utc) - begun
                    ).total_seconds(),
                    package_size_bytes=prepared.package_size,
                    errors=[],
                    operation_id=op_id,
                    stage="complete",
                )

            if target_ident is None:
                raise RuntimeError(
                    f"restore operation {op_id} remains needs_verification: "
                    "target database is not reachable, so its state cannot "
                    "be verified"
                )
            empty = _database_is_empty(target_database_url)
            if empty is None:
                raise RuntimeError(
                    f"restore operation {op_id} remains needs_verification: "
                    "target database empty state could not be determined"
                )
            log_payload = _operation_log_payload(
                operation_id=op_id,
                package_digest=prepared.package_digest,
                target_blobs=target_blobs,
                target_database_url=target_database_url,
                target_ident=target_ident,
                stage=stage,
            )
            if empty:
                _write_restore_operation_log(
                    target_blobs, log_payload, stage="blobs_published"
                )
                return RestoreResult(
                    ok=False,
                    database_restored=False,
                    blobs_restored=len(inventory),
                    duration_seconds=(
                        datetime.now(timezone.utc) - begun
                    ).total_seconds(),
                    package_size_bytes=prepared.package_size,
                    errors=[
                        "target database verified still empty; the restore "
                        "may be retried via resume"
                    ],
                    operation_id=op_id,
                    stage="blobs_published",
                )
            try:
                _verify_restored_state(
                    target_database_url,
                    target_blobs,
                    inventory,
                    db_reachable=True,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"restore operation {op_id} remains needs_verification: "
                    f"{exc}"
                ) from exc
            _write_restore_operation_log(
                target_blobs, log_payload, stage="complete"
            )
            return RestoreResult(
                ok=True,
                database_restored=True,
                blobs_restored=len(inventory),
                duration_seconds=(
                    datetime.now(timezone.utc) - begun
                ).total_seconds(),
                package_size_bytes=prepared.package_size,
                errors=[],
                operation_id=op_id,
                stage="complete",
            )
        finally:
            _safe_rmtree(work_dir)


def cleanup_restore_operation(
    target_blobs_dir: str | Path,
    *,
    operation_id: str,
) -> int:
    """Remove one unfinished operation's files from its target blob root.

    Requires the operation id and verifies ownership against the
    operation log before deleting anything. Only operations in a stage
    that proves the database commit did not happen (see
    ``_CLEANUP_ELIGIBLE_RESTORE_STAGES``) may be cleaned up; a completed
    or commit-ambiguous operation's files may be the live restored data,
    not cleanup material. Returns the number of files removed.
    """
    op_id = _validate_operation_id(operation_id)
    target_blobs = _resolve_restore_target(target_blobs_dir)
    op_log = (
        _read_restore_operation_log(target_blobs) if target_blobs.is_dir() else None
    )
    if op_log is None:
        raise RuntimeError(
            "restore cleanup refused: no restore operation log in target: "
            f"{target_blobs}"
        )
    removed = 0
    with _backup_destination_lock(target_blobs):
        # Re-read and re-verify the operation log under the destination
        # lock: the stage that authorizes deletion must be the stage in
        # effect while the lock is held, not a stale pre-lock snapshot —
        # the operation may have completed (or entered
        # needs_verification) while cleanup waited for the lock.
        op_log = (
            _read_restore_operation_log(target_blobs)
            if target_blobs.is_dir()
            else None
        )
        if op_log is None:
            raise RuntimeError(
                "restore cleanup refused: no restore operation log in "
                f"target: {target_blobs}"
            )
        _assert_operation_log_matches(
            op_log, operation_id=op_id, target_blobs=target_blobs
        )
        stage = str(op_log.get("stage") or "")
        if stage not in _CLEANUP_ELIGIBLE_RESTORE_STAGES:
            raise RuntimeError(
                f"restore cleanup refused: operation {op_id} is in stage "
                f"{stage!r}, which does not prove the database commit did "
                "not happen; its files may be the restored data"
            )
        # Delete ONLY this operation's own artifacts: the operation log
        # (and its atomic-write temp files), this operation's staging
        # directory, and the *.blob files it published. Anything else in
        # the target is foreign to this operation — the directory may be
        # a live blob root or shared with another operation — so refuse
        # and delete nothing instead of wiping every child.
        staging_name = f"{_RESTORE_STAGING_PREFIX}{op_id}"
        own_files: list[Path] = []
        for path in sorted(target_blobs.rglob("*")):
            rel = path.relative_to(target_blobs)
            first = rel.parts[0]
            if path.is_symlink():
                raise RuntimeError(
                    "restore cleanup refused: foreign entry in restore "
                    f"target is not part of operation {op_id}: "
                    f"{rel.as_posix()} (symlink)"
                )
            if path.is_dir():
                if (
                    first.startswith(".")
                    and first != staging_name
                    and first != _RESTORE_OPERATION_LOG_FILENAME
                    and not first.startswith(
                        _RESTORE_OPERATION_LOG_FILENAME + ".tmp-"
                    )
                ):
                    raise RuntimeError(
                        "restore cleanup refused: foreign entry in restore "
                        f"target is not part of operation {op_id}: "
                        f"{rel.as_posix()}"
                    )
                continue
            if (
                first == _RESTORE_OPERATION_LOG_FILENAME
                or first.startswith(_RESTORE_OPERATION_LOG_FILENAME + ".tmp-")
                or first == staging_name
                or (
                    path.name.endswith(".blob")
                    and not any(part.startswith(".") for part in rel.parts)
                )
            ):
                own_files.append(path)
            else:
                raise RuntimeError(
                    "restore cleanup refused: foreign file in restore "
                    f"target is not part of operation {op_id}: "
                    f"{rel.as_posix()}"
                )
        for path in own_files:
            path.unlink()
            removed += 1
        staging_dir = target_blobs / staging_name
        if staging_dir.is_dir():
            shutil.rmtree(staging_dir)
        # Prune directories left empty by the deletions (deepest first);
        # directories still holding anything are kept.
        for dirpath in sorted(
            (p for p in target_blobs.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            try:
                dirpath.rmdir()
            except OSError:
                pass
        _fsync_dir(target_blobs)
    return removed
