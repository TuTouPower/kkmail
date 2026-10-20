"""Shared fixtures / env defaults for mail-core unit tests."""

from __future__ import annotations

import base64
import os

# BlobStore and API lifespan refuse to start without keys — give tests a fixed key.
_TEST_BLOB_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ.setdefault("MAIL_CORE_BLOB_KEY_V1", _TEST_BLOB_KEY)
os.environ.setdefault("MAIL_CORE_BLOB_ACTIVE_VERSION", "1")
