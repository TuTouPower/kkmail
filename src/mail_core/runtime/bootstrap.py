"""Per-install secret bootstrap for a single-user data directory (desktop / local).

When ``MAIL_CORE_DATA_DIR`` is set, missing secrets are generated once with
``secrets``/``os.urandom`` and persisted with mode 0600 inside that directory.
Environment variables always win. Nothing here ever falls back to a constant.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import time
from pathlib import Path

import bcrypt

INITIAL_PASSWORD_FILE = "initial-password.txt"
_SECRET_FILE_WRITE_TIMEOUT_S = 5.0
_BCRYPT_HASH_BYTES = 60


def _restrict_secret_file_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "could not restrict secret file permissions for %s: %s", path, exc
        )


def _read_or_create(path: Path, factory) -> str:
    if path.is_file():
        _restrict_secret_file_permissions(path)
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = factory()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _restrict_secret_file_permissions(path)
        deadline = time.monotonic() + _SECRET_FILE_WRITE_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                existing = path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                existing = ""
            if existing:
                return existing
            time.sleep(0.01)
        raise RuntimeError(f"secret file {path} was created but remained empty")

    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
    return value


def _wait_for_bcrypt_hash(path: Path) -> None:
    deadline = time.monotonic() + _SECRET_FILE_WRITE_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            if path.is_file() and path.stat().st_size == _BCRYPT_HASH_BYTES:
                return
        except OSError:
            pass
        time.sleep(0.01)
    raise RuntimeError(f"login password hash file {path} was not fully written")


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

    def setdefault(name: str, value_factory) -> None:
        if (env.get(name) or "").strip():
            return
        env[name] = value_factory()
        applied[name] = "generated-or-loaded"

    setdefault("MAIL_CORE_SECRET_KEY", lambda: _read_or_create(secrets_dir / "session.key", lambda: secrets.token_hex(32)))
    if not (env.get("MAIL_CORE_BLOB_KEYS") or "").strip():
        setdefault("MAIL_CORE_BLOB_KEY_V1", lambda: _read_or_create(secrets_dir / "blob-v1.key", _b64_key))
    setdefault("MAIL_CORE_BACKUP_KEY", lambda: _read_or_create(secrets_dir / "backup.key", _b64_key))
    setdefault("MAIL_CORE_BLOB_ROOT", lambda: str(root / "blobs"))
    setdefault("MAIL_CORE_BACKUP_DIR", lambda: str(root / "backups"))

    if not any((env.get(k) or "").strip() for k in ("MAIL_CORE_LOGIN_PASSWORD_HASH", "MAIL_CORE_LOGIN_PASSWORD")):
        env.setdefault("MAIL_CORE_PASSWORD_HASH_PATH", str(hash_path))
        if hash_path.is_file():
            _wait_for_bcrypt_hash(hash_path)
        else:
            initial = _read_or_create(
                root / INITIAL_PASSWORD_FILE,
                lambda: secrets.token_urlsafe(12),
            )
            from mail_core.security.auth import _bcrypt_password_bytes

            hashed = bcrypt.hashpw(_bcrypt_password_bytes(initial), bcrypt.gensalt())
            try:
                fd = os.open(hash_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                _restrict_secret_file_permissions(hash_path)
            else:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(hashed)
            _wait_for_bcrypt_hash(hash_path)
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
