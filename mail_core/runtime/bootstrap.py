"""Per-install secret bootstrap for a single-user data directory (desktop / local).

When ``MAIL_CORE_DATA_DIR`` is set, missing secrets are generated once with
``secrets``/``os.urandom`` and persisted with mode 0600 inside that directory.
Environment variables always win. Nothing here ever falls back to a constant.
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

import bcrypt

INITIAL_PASSWORD_FILE = "initial-password.txt"


def _read_or_create(path: Path, factory) -> str:
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = factory()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
    return value


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

    hash_path = secrets_dir / "login-password.bcrypt"
    if not any((env.get(k) or "").strip() for k in ("MAIL_CORE_LOGIN_PASSWORD_HASH", "MAIL_CORE_LOGIN_PASSWORD")):
        env.setdefault("MAIL_CORE_PASSWORD_HASH_PATH", str(hash_path))
        if not hash_path.is_file():
            initial = secrets.token_urlsafe(12)
            hashed = bcrypt.hashpw(initial.encode("utf-8"), bcrypt.gensalt())
            fd = os.open(hash_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(hashed)
            _read_or_create(root / INITIAL_PASSWORD_FILE, lambda: initial)
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
