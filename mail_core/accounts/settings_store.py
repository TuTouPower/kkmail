"""Non-secret app settings. Passwords/tokens must never be stored or returned here."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import AppSetting

# Keys the SPA may read/write. Anything else is ignored on write / omitted on read.
PUBLIC_SETTING_KEYS = frozenset(
    {
        "app_timezone",
        "mail_fetch_timeout_seconds",
    }
)

# Never return these even if somehow present in the table.
SECRET_SETTING_PREFIXES = (
    "password",
    "secret",
    "token",
    "api_key",
    "client_secret",
    "refresh",
    "login_password",
)


def _is_secret_key(key: str) -> bool:
    k = key.lower()
    return any(p in k for p in SECRET_SETTING_PREFIXES)


def get_public_settings(session: Session) -> dict[str, str]:
    rows = session.scalars(select(AppSetting)).all()
    out: dict[str, str] = {}
    for row in rows:
        if _is_secret_key(row.key):
            continue
        if row.key in PUBLIC_SETTING_KEYS:
            out[row.key] = row.value
    return out


def update_public_settings(session: Session, patch: dict[str, str]) -> dict[str, str]:
    """Apply a patch of public settings. Unknown or secret keys raise ValueError."""
    rejected = sorted(k for k in patch if k not in PUBLIC_SETTING_KEYS or _is_secret_key(k))
    if rejected:
        raise ValueError(f"unsupported setting keys: {', '.join(rejected)}")
    for key, value in patch.items():
        row = session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=str(value))
            session.add(row)
        else:
            row.value = str(value)
    session.flush()
    return get_public_settings(session)
