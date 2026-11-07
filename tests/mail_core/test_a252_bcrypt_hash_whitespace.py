"""A252 / A15: _validate_bcrypt_hash must tolerate whitespace around a valid hash.

Old code compared the raw file size to exactly 60 bytes, so a hash file
written by external tooling (``echo $hash > file`` -> 61 bytes with a
trailing newline) made every bootstrap wait the full timeout and then
hard-fail, even though the auth side reads the same file with strip().
Under A15, validation happens immediately without busy-wait sleeping.
"""

from __future__ import annotations

import bcrypt
import pytest

from mail_core.runtime.bootstrap import _validate_bcrypt_hash


def _hash_bytes() -> bytes:
    hashed = bcrypt.hashpw(b"some-password", bcrypt.gensalt())
    assert len(hashed) == 60
    assert hashed.startswith(b"$2")
    return hashed


def test_wait_accepts_hash_with_trailing_newline(tmp_path):
    path = tmp_path / "login-password.bcrypt"
    path.write_bytes(_hash_bytes() + b"\n")
    _validate_bcrypt_hash(path)  # must return, not raise


def test_wait_accepts_hash_with_surrounding_whitespace(tmp_path):
    path = tmp_path / "login-password.bcrypt"
    path.write_bytes(b"  " + _hash_bytes() + b" \n")
    _validate_bcrypt_hash(path)


def test_wait_accepts_bare_60_byte_hash(tmp_path):
    path = tmp_path / "login-password.bcrypt"
    path.write_bytes(_hash_bytes())
    _validate_bcrypt_hash(path)


def test_wait_still_rejects_wrong_prefix(tmp_path):
    path = tmp_path / "login-password.bcrypt"
    path.write_bytes(b"x" * 60 + b"\n")
    with pytest.raises(RuntimeError):
        _validate_bcrypt_hash(path)


def test_wait_still_rejects_wrong_length(tmp_path):
    path = tmp_path / "login-password.bcrypt"
    path.write_bytes(b"$2b$short\n")
    with pytest.raises(RuntimeError):
        _validate_bcrypt_hash(path)


def test_wait_still_rejects_missing_file(tmp_path):
    with pytest.raises(RuntimeError):
        _validate_bcrypt_hash(tmp_path / "missing.bcrypt")
