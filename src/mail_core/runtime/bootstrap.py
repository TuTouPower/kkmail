"""Per-install secret bootstrap for a single-user data directory (desktop / local).

When ``MAIL_CORE_DATA_DIR`` is set, missing secrets are generated once with
``secrets``/``os.urandom`` and persisted with mode 0600 inside that directory.
Environment variables always win. Nothing here ever falls back to a constant.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import logging
import os
import secrets
import sys
import threading
import uuid
from pathlib import Path
from typing import Callable, Iterator

import bcrypt

INITIAL_PASSWORD_FILE = "initial-password.txt"
_BCRYPT_HASH_BYTES = 60

_thread_local = threading.local()


def _restrict_secret_file_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "could not restrict secret file permissions for %s: %s", path, exc
        )


def _fsync_dir(dir_path: Path) -> None:
    try:
        dir_fd = os.open(dir_path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        try:
            os.close(dir_fd)
        except OSError:
            pass


@contextlib.contextmanager
def _bootstrap_lock(secrets_dir: Path) -> Iterator[None]:
    secrets_dir.mkdir(parents=True, exist_ok=True)
    lock_path = (secrets_dir / ".bootstrap.lock").resolve()

    if not hasattr(_thread_local, "locks"):
        _thread_local.locks = {}

    if _thread_local.locks:
        yield
        return

    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _restrict_secret_file_permissions(lock_path)
        if sys.platform == "win32":
            import msvcrt

            try:
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                    os.fsync(fd)
            except OSError:
                pass
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        elif hasattr(fcntl, "flock"):
            fcntl.flock(fd, fcntl.LOCK_EX)

        _thread_local.locks[lock_path] = fd
        try:
            yield
        finally:
            del _thread_local.locks[lock_path]
            try:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                elif hasattr(fcntl, "flock"):
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        os.close(fd)


def _atomic_write_secret(path: Path, content_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{uuid.uuid4().hex}")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _restrict_secret_file_permissions(tmp_path)
        with open(fd, "wb", closefd=True) as fh:
            fh.write(content_bytes)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        _restrict_secret_file_permissions(path)
        _fsync_dir(path.parent)
    except BaseException:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def _read_or_create(path: Path, factory: Callable[[], str]) -> str:
    with _bootstrap_lock(path.parent):
        if path.exists():
            if not path.is_file():
                raise RuntimeError(f"secret path {path} exists but is not a regular file")
            _restrict_secret_file_permissions(path)
            try:
                value = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise RuntimeError(f"cannot read secret file {path}: {exc}") from exc
            if not value:
                raise RuntimeError(f"secret file {path} exists but is empty or corrupted")
            return value

        value = factory()
        if not value or not value.strip():
            raise RuntimeError(f"secret factory produced empty value for {path}")
        clean_value = value.strip()
        _atomic_write_secret(path, (clean_value + "\n").encode("utf-8"))
        return clean_value


def _validate_bcrypt_hash(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"login password hash file {path} does not exist")
    if not path.is_file():
        raise RuntimeError(f"login password hash path {path} is not a regular file")
    try:
        content = path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError as exc:
        raise RuntimeError(f"cannot read login password hash file {path}: {exc}") from exc
    if len(content) != _BCRYPT_HASH_BYTES or not content.startswith("$2"):
        raise RuntimeError(f"login password hash file {path} is invalid or corrupted")


def _b64_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def bootstrap_data_dir(data_dir: str | os.PathLike[str], env: dict[str, str] | None = None) -> dict[str, str]:
    """Fill ``env`` (default ``os.environ``) with per-install secrets. Returns what was set."""
    env = os.environ if env is None else env
    root = Path(data_dir)
    secrets_dir = root / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(secrets_dir, 0o700)
    except OSError:  # pragma: no cover - Windows ACLs
        pass

    with _bootstrap_lock(secrets_dir):
        hash_path = secrets_dir / "login-password.bcrypt"
        for path in (
            secrets_dir / "session.key",
            secrets_dir / "blob-v1.key",
            secrets_dir / "backup.key",
            hash_path,
            root / INITIAL_PASSWORD_FILE,
        ):
            if path.is_file():
                _restrict_secret_file_permissions(path)

        applied: dict[str, str] = {}

        def setdefault(name: str, value_factory: Callable[[], str]) -> None:
            if (env.get(name) or "").strip():
                return
            env[name] = value_factory()
            applied[name] = "generated-or-loaded"

        setdefault(
            "MAIL_CORE_SECRET_KEY",
            lambda: _read_or_create(secrets_dir / "session.key", lambda: secrets.token_hex(32)),
        )
        if not (env.get("MAIL_CORE_BLOB_KEYS") or "").strip():
            setdefault("MAIL_CORE_BLOB_KEY_V1", lambda: _read_or_create(secrets_dir / "blob-v1.key", _b64_key))
        setdefault("MAIL_CORE_BACKUP_KEY", lambda: _read_or_create(secrets_dir / "backup.key", _b64_key))
        setdefault("MAIL_CORE_BLOB_ROOT", lambda: str(root / "blobs"))
        setdefault("MAIL_CORE_BACKUP_DIR", lambda: str(root / "backups"))

        if not any((env.get(k) or "").strip() for k in ("MAIL_CORE_LOGIN_PASSWORD_HASH", "MAIL_CORE_LOGIN_PASSWORD")):
            env.setdefault("MAIL_CORE_PASSWORD_HASH_PATH", str(hash_path))
            if hash_path.exists():
                _validate_bcrypt_hash(hash_path)
            else:
                initial_pw_path = root / INITIAL_PASSWORD_FILE
                initial = _read_or_create(
                    initial_pw_path,
                    lambda: secrets.token_urlsafe(12),
                )
                from mail_core.security.auth import _bcrypt_password_bytes

                hashed = bcrypt.hashpw(_bcrypt_password_bytes(initial), bcrypt.gensalt())
                _atomic_write_secret(hash_path, hashed)
                applied["MAIL_CORE_PASSWORD_HASH_PATH"] = "initial-password-generated"
        return applied


def clear_initial_password(data_dir: str | os.PathLike[str] | None) -> None:
    """Remove the one-time initial password file after the user changes it."""
    if not data_dir:
        return
    try:
        (Path(data_dir) / INITIAL_PASSWORD_FILE).unlink()
    except FileNotFoundError:
        pass
