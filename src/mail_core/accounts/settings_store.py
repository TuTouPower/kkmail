"""Non-secret app settings. Passwords/tokens must never be stored or returned here."""

from __future__ import annotations

import zoneinfo
from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import AppSetting

# Keys the SPA may read/write. Unknown or secret keys are rejected on write (raise ValueError);
# omitted on read.
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


def get_app_setting(session: Session, key: str, default: str | None = None) -> str | None:
    """Retrieve a single non-secret setting value by key."""
    row = session.get(AppSetting, key)
    if row is None or _is_secret_key(row.key):
        return default
    return row.value


def get_fetch_timeout_seconds(session: Session, default: float = 30.0) -> float:
    """Effective mail fetch timeout in seconds for provider connections."""
    val = get_app_setting(session, "mail_fetch_timeout_seconds")
    if val:
        try:
            sec = float(val)
            if sec > 0:
                return sec
        except ValueError:
            pass
    return default


def update_public_settings(session: Session, patch: dict[str, str]) -> dict[str, str]:
    """Apply a patch of public settings. Unknown or secret keys raise ValueError."""
    rejected = sorted(k for k in patch if k not in PUBLIC_SETTING_KEYS or _is_secret_key(k))
    if rejected:
        raise ValueError(f"unsupported setting keys: {', '.join(rejected)}")

    if "mail_fetch_timeout_seconds" in patch:
        try:
            timeout_val = float(patch["mail_fetch_timeout_seconds"])
            if timeout_val <= 0:
                raise ValueError("mail_fetch_timeout_seconds must be positive")
        except (ValueError, TypeError):
            raise ValueError("mail_fetch_timeout_seconds must be a positive number")

    if "app_timezone" in patch:
        tz_name = str(patch["app_timezone"]).strip()
        if tz_name:
            try:
                zoneinfo.ZoneInfo(tz_name)
            except Exception:
                raise ValueError(f"invalid IANA timezone: {tz_name}")

    for key, value in patch.items():
        row = session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=str(value))
            session.add(row)
        else:
            row.value = str(value)
    session.flush()
    return get_public_settings(session)
