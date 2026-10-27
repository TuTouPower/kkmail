"""mail-core security defaults and auth (architecture §11 / M5)."""

from mail_core.security.defaults import require_encrypted_volume_docs
from mail_core.security.redact import redact, safe_error, safe_provider_summary

__all__ = ["require_encrypted_volume_docs", "redact", "safe_error", "safe_provider_summary"]
