"""Controlled normalization of application-private data permissions.

This is a maintenance entry point, not a startup repair hook.  Callers run
it explicitly (inside the application-uid container for Docker volumes, or
on the host for host-owned backup directories) so permission drift left by
older releases or restore paths can be corrected without depending on the
process umask or silently following symlinks.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from mail_core.blobs.private_fs import PrivatePathError, make_private_dir

DEFAULT_FILE_MODE = 0o600
DEFAULT_DIR_MODE = 0o700


class PermissionNormalizationError(RuntimeError):
    """The tree contains an entry that cannot be normalized safely."""


def _require_owner(path: Path, st: os.stat_result, owner_uid: int, owner_gid: int) -> None:
    if st.st_uid != owner_uid or st.st_gid != owner_gid:
        raise PermissionNormalizationError(
            f"refusing to normalize {path}: owned by {st.st_uid}:{st.st_gid}, "
            f"expected application owner {owner_uid}:{owner_gid}; run as the "
            "application uid"
        )


def normalize_private_permissions(
    root: str | Path,
    *,
    file_mode: int = DEFAULT_FILE_MODE,
    dir_mode: int = DEFAULT_DIR_MODE,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
    target_uid: int | None = None,
    target_gid: int | None = None,
) -> dict[str, object]:
    """Normalize ``root`` to private file/directory modes.

    Without ``target_uid``/``target_gid``, every entry must already belong to
    ``owner_uid:owner_gid`` (defaults to the current process); this is the
    safe mode-normalization path.  Supplying both target ids performs an
    explicit ``chown`` as well, which requires root plus
    CHOWN/FOWNER/DAC_OVERRIDE (DAC_OVERRIDE to traverse a foreign 0700 tree);
    an operation that cannot do so fails closed.  Symlinks and non-regular files are
    refused rather than followed.  Returns a small JSON-serializable summary.
    """
    path_root = Path(root)
    if path_root.is_symlink():
        raise PermissionNormalizationError(f"refusing symlink root: {path_root}")
    if not path_root.is_dir():
        raise PermissionNormalizationError(f"root is not a directory: {path_root}")
    if (target_uid is None) != (target_gid is None):
        raise PermissionNormalizationError(
            "target_uid and target_gid must be supplied together"
        )
    chown_target = target_uid is not None
    expected_uid = target_uid if chown_target else (os.getuid() if owner_uid is None else owner_uid)
    expected_gid = target_gid if chown_target else (os.getgid() if owner_gid is None else owner_gid)

    def _apply_owner(path: Path) -> None:
        if not chown_target:
            return
        try:
            os.chown(path, expected_uid, expected_gid)
        except OSError as exc:
            raise PermissionNormalizationError(
                f"cannot chown {path} to {expected_uid}:{expected_gid}: {exc}; "
                "run as root with CHOWN/FOWNER/DAC_OVERRIDE for an explicit owner migration"
            ) from exc

    def _walk_error(exc: OSError) -> None:
        raise PermissionNormalizationError(
            f"failed to scan {exc.filename or path_root}: {exc}"
        )

    files = 0
    directories = 0
    for dirpath, dirnames, filenames in os.walk(
        path_root, topdown=True, followlinks=False, onerror=_walk_error
    ):
        current = Path(dirpath)
        for name in list(dirnames):
            child = current / name
            st = child.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise PermissionNormalizationError(f"refusing symlink directory: {child}")
            if not stat.S_ISDIR(st.st_mode):
                raise PermissionNormalizationError(f"not a directory: {child}")
            _apply_owner(child)
            _require_owner(child, child.lstat(), expected_uid, expected_gid)
            try:
                make_private_dir(child, strict=True)
                if dir_mode != 0o700:
                    child.chmod(dir_mode)
            except (OSError, PrivatePathError) as exc:
                raise PermissionNormalizationError(str(exc)) from exc
            directories += 1
        for name in filenames:
            child = current / name
            st = child.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise PermissionNormalizationError(f"refusing symlink file: {child}")
            if not stat.S_ISREG(st.st_mode):
                raise PermissionNormalizationError(f"not a regular file: {child}")
            _apply_owner(child)
            _require_owner(child, child.lstat(), expected_uid, expected_gid)
            child.chmod(file_mode)
            files += 1

    root_stat = path_root.lstat()
    if stat.S_ISLNK(root_stat.st_mode):
        raise PermissionNormalizationError(f"refusing symlink root: {path_root}")
    _apply_owner(path_root)
    _require_owner(path_root, path_root.lstat(), expected_uid, expected_gid)
    try:
        make_private_dir(path_root, strict=True)
        if dir_mode != 0o700:
            path_root.chmod(dir_mode)
    except (OSError, PrivatePathError) as exc:
        raise PermissionNormalizationError(str(exc)) from exc
    directories += 1
    return {
        "root": str(path_root),
        "files": files,
        "directories": directories,
        "file_mode": oct(file_mode),
        "dir_mode": oct(dir_mode),
        "owner_uid": expected_uid,
        "owner_gid": expected_gid,
        "ownership_changed": chown_target,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mail_core.blobs.permissions",
        description="Normalize an application-private data tree to 0700/0600.",
    )
    parser.add_argument(
        "root",
        help="directory to normalize; entries must already belong to the current uid/gid",
    )
    parser.add_argument("--file-mode", default=oct(DEFAULT_FILE_MODE))
    parser.add_argument("--dir-mode", default=oct(DEFAULT_DIR_MODE))
    parser.add_argument("--target-uid", type=int)
    parser.add_argument("--target-gid", type=int)
    args = parser.parse_args(argv)
    try:
        file_mode = int(str(args.file_mode), 8)
        dir_mode = int(str(args.dir_mode), 8)
        result = normalize_private_permissions(
            args.root,
            file_mode=file_mode,
            dir_mode=dir_mode,
            target_uid=args.target_uid,
            target_gid=args.target_gid,
        )
    except (OSError, ValueError, PermissionNormalizationError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
