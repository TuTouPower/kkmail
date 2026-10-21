"""Safe HTTP header helpers for mail-core responses."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import quote

# Control chars, quotes, backslash, path/header separators, and colon (header injection bait).
_BAD = re.compile(r'[\x00-\x1f\x7f"\\/;:]')


def content_disposition_attachment(filename: str | None) -> str:
    """Build Content-Disposition with RFC 5987 ``filename*`` (no header injection).

    Strips CR/LF/quotes from the ASCII fallback, collapses path components to a
    basename, and percent-encodes the UTF-8 ``filename*`` form so browsers get
    the real name without allowing response-splitting.
    """
    raw = (filename or "attachment").strip() or "attachment"
    # Never allow directory components into the header (``a/../../x.pdf`` → ``x.pdf``).
    base = PurePosixPath(raw.replace("\\", "/")).name.strip() or "attachment"
    # Drop C0 controls from the value that will be percent-encoded as well.
    base_clean = re.sub(r"[\x00-\x1f\x7f]", "", base) or "attachment"
    ascii_candidate = base_clean.encode("ascii", "replace").decode("ascii")
    ascii_name = re.sub(r'[\x00-\x1f\x7f"\\/;:?]', "_", ascii_candidate)[:180].strip() or "attachment"
    # Encode the cleaned basename so filename* cannot smuggle CR/LF or separators.
    encoded = quote(base_clean, safe="")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'
