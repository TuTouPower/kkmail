from __future__ import annotations

import json
import os
import stat

import pytest

import mail_core.blobs.permissions as permissions
from mail_core.blobs.private_fs import PrivatePathError, make_private_chain
from mail_core.blobs.permissions import (
    PermissionNormalizationError,
    main,
    normalize_private_permissions,
)


def _modes(path):
    return stat.S_IMODE(path.lstat().st_mode)


def test_normalize_private_permissions_tightens_tree(tmp_path):
    root = tmp_path / "blobs"
    shard = root / "aa" / "bb"
    shard.mkdir(parents=True)
    blob = shard / "message.blob"
    blob.write_bytes(b"ciphertext")
    shard.chmod(0o755)
    root.chmod(0o755)
    blob.chmod(0o644)

    result = normalize_private_permissions(root)

    assert _modes(root) == 0o700
    assert _modes(root / "aa") == 0o700
    assert _modes(shard) == 0o700
    assert _modes(blob) == 0o600
    assert result["files"] == 1
    assert result["directories"] == 3


def test_normalize_private_permissions_refuses_symlinks(tmp_path):
    root = tmp_path / "blobs"
    root.mkdir()
    target = tmp_path / "outside"
    target.write_bytes(b"not a blob")
    (root / "link").symlink_to(target)

    with pytest.raises(PermissionNormalizationError, match="symlink"):
        normalize_private_permissions(root)


def test_normalize_private_permissions_refuses_foreign_owner(tmp_path):
    root = tmp_path / "blobs"
    root.mkdir()

    with pytest.raises(PermissionNormalizationError, match="application owner"):
        normalize_private_permissions(
            root, owner_uid=os.getuid() + 1, owner_gid=os.getgid()
        )


def test_normalize_private_permissions_refuses_unreadable_subtree(tmp_path):
    root = tmp_path / "blobs"
    shard = root / "aa"
    shard.mkdir(parents=True)
    (shard / "message.blob").write_bytes(b"ciphertext")
    root.chmod(0o000)
    try:
        with pytest.raises(PermissionNormalizationError, match="failed to scan"):
            normalize_private_permissions(root)
    finally:
        root.chmod(0o700)


def test_normalize_cli_reports_summary(tmp_path, capsys):
    root = tmp_path / "blobs"
    shard = root / "aa"
    shard.mkdir(parents=True)
    (shard / "message.blob").write_bytes(b"ciphertext")
    root.chmod(0o755)
    shard.chmod(0o755)
    (shard / "message.blob").chmod(0o644)

    assert main([str(root)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["files"] == 1
    assert output["directories"] == 2
    assert _modes(root) == 0o700
    assert _modes(shard) == 0o700
    assert _modes(shard / "message.blob") == 0o600


def test_normalize_can_chown_to_explicit_target(tmp_path, monkeypatch):
    root = tmp_path / "blobs"
    shard = root / "aa"
    shard.mkdir(parents=True)
    (shard / "message.blob").write_bytes(b"ciphertext")
    calls = []
    monkeypatch.setattr(
        permissions.os,
        "chown",
        lambda path, uid, gid: calls.append((str(path), uid, gid)),
    )

    result = normalize_private_permissions(
        root, target_uid=os.getuid(), target_gid=os.getgid()
    )

    assert result["ownership_changed"] is True
    assert calls
    assert _modes(root) == 0o700
    assert _modes(shard / "message.blob") == 0o600


def test_normalize_chown_failure_is_actionable(tmp_path, monkeypatch):
    root = tmp_path / "blobs"
    root.mkdir()
    monkeypatch.setattr(
        permissions.os,
        "chown",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )

    with pytest.raises(PermissionNormalizationError, match="CHOWN/FOWNER/DAC_OVERRIDE"):
        normalize_private_permissions(root, target_uid=1, target_gid=1)


def test_make_private_chain_accepts_symlinked_ancestor(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    root = link / "root"
    root.mkdir()

    make_private_chain(root / "aa" / "bb", root)

    assert _modes(root / "aa") == 0o700
    assert _modes(root / "aa" / "bb") == 0o700


def test_make_private_chain_refuses_outside_path_before_creating_it(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside" / "aa"

    with pytest.raises(PrivatePathError, match="outside private root"):
        make_private_chain(outside, root)

    assert not outside.exists()
