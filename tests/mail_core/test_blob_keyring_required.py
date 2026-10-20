"""Blob keyring must refuse to load without configured keys."""

from __future__ import annotations

import base64
import os

import pytest

from mail_core.blobs.crypto import BlobCryptoError, load_keyring_from_env


def test_load_keyring_raises_when_no_keys():
    with pytest.raises(BlobCryptoError, match="blob encryption keys required"):
        load_keyring_from_env(env={})


def test_load_keyring_raises_when_empty_strings():
    with pytest.raises(BlobCryptoError, match="blob encryption keys required"):
        load_keyring_from_env(env={"MAIL_CORE_BLOB_KEYS": "", "MAIL_CORE_BLOB_KEY_V1": ""})


def test_load_keyring_from_v1():
    key = base64.b64encode(os.urandom(32)).decode()
    kr = load_keyring_from_env(env={"MAIL_CORE_BLOB_KEY_V1": key})
    assert kr.active_version == 1
    assert len(kr.get(1)) == 32


def test_load_keyring_rejects_wrong_length():
    short = base64.b64encode(b"too-short").decode()
    with pytest.raises(BlobCryptoError, match="32 bytes"):
        load_keyring_from_env(env={"MAIL_CORE_BLOB_KEY_V1": short})


def test_worker_run_fails_fast_without_keys(monkeypatch):
    monkeypatch.delenv("MAIL_CORE_BLOB_KEY_V1", raising=False)
    monkeypatch.delenv("MAIL_CORE_BLOB_KEYS", raising=False)
    from mail_core.worker import main as worker_main

    with pytest.raises(BlobCryptoError, match="blob encryption keys required"):
        worker_main.run(poll_interval_s=0.01)
