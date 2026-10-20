"""Safe HTTP header helpers for mail-core responses."""

from __future__ import annotations

import re
from urllib.parse import quote

_BAD = re.compile(r'[\x00-\x1f\x7f"\\/;]')


def content_disposition_attachment(filename: str | None) -> str:
    """Build Content-Disposition without CR/LF/quote injection."""
    raw = (filename or "attachment").strip() or "attachment"
    ascii_name = _BAD.sub("_", raw)[:180] or "attachment"
    encoded = quote(raw, safe="")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'
