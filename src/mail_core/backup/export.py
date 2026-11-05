"""Export a container-private backup package to the host-owned staging area.

The backup container runs with the application uid and writes its sealed
package into its own writable layer.  The host-side process that runs this
module owns the destination directory; copying the package here is the
explicit identity boundary crossing.  Everything is verified before the
package is published as a rollback source.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Callable

from mail_core.backup.package import verify_backup_package
from mail_core.blobs.private_fs import PrivatePathError, make_private_dir

DOCKER_COPY = Callable[[str, str], None]


class BackupExportError(RuntimeError):
    """A container backup package could not be exported or verified."""


def _docker_cp(source: str, destination: str) -> None:
    try:
        subprocess.run(
            ["docker", "cp", source, destination],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise BackupExportError(
            f"docker cp failed ({exc.returncode}): {detail[:500]}"
        ) from exc


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _secure_exported_tree(package_dir: Path) -> int:
    """Make the host copy operator-owned and private; refuse symlinks.

    ``docker cp`` runs in the operator's context, so a foreign owner means
    the identity crossing did not happen as expected.  Fail closed instead
    of publishing a package the operator cannot trust or read.
    """
    uid = os.getuid()
    gid = os.getgid()

    def _walk_error(exc: OSError) -> None:
        raise BackupExportError(
            f"failed to scan exported package {exc.filename or package_dir}: {exc}"
        )

    members = 0
    for dirpath, dirnames, filenames in os.walk(
        package_dir, topdown=True, followlinks=False, onerror=_walk_error
    ):
        current = Path(dirpath)
        for name in list(dirnames):
            child = current / name
            st = child.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise BackupExportError(f"exported package contains a symlink: {child}")
            if not stat.S_ISDIR(st.st_mode):
                raise BackupExportError(f"exported package contains a non-directory: {child}")
            if st.st_uid != uid or st.st_gid != gid:
                raise BackupExportError(
                    f"exported package entry has foreign owner "
                    f"{st.st_uid}:{st.st_gid}: {child}"
                )
            child.chmod(0o700)
            members += 1
        for name in filenames:
            child = current / name
            st = child.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise BackupExportError(f"exported package contains a symlink: {child}")
            if not stat.S_ISREG(st.st_mode):
                raise BackupExportError(
                    f"exported package contains a non-regular file: {child}"
                )
            if st.st_uid != uid or st.st_gid != gid:
                raise BackupExportError(
                    f"exported package entry has foreign owner "
                    f"{st.st_uid}:{st.st_gid}: {child}"
                )
            child.chmod(0o600)
            members += 1

    st = package_dir.lstat()
    if st.st_uid != uid or st.st_gid != gid:
        raise BackupExportError("exported package directory has a foreign owner")
    package_dir.chmod(0o700)
    return members


def export_container_package(
    *,
    container: str,
    staging_dir: str | Path,
    backup_dir: str | Path,
    allow_stub: bool = False,
    docker_cp: DOCKER_COPY | None = None,
) -> Path:
    """Export ``container:/backup/package`` and publish it atomically.

    ``staging_dir`` and ``backup_dir`` are both host-owned directories.  The
    package is copied into ``staging_dir/package``, checked for symlinks and
    foreign ownership, normalized to 0700/0600, verified with the restore
    verifier, then renamed to ``backup_dir/package``.  On any failure no
    package exists under ``backup_dir``.
    """
    if not container or ":" in container:
        raise BackupExportError(f"invalid backup container name: {container!r}")
    staging = Path(staging_dir)
    backup = Path(backup_dir)
    if staging.is_symlink() or backup.is_symlink():
        raise BackupExportError("refusing symlink staging/backup directory")
    make_private_dir(staging, strict=True)
    package_dir = staging / "package"
    if package_dir.exists() or package_dir.is_symlink():
        raise BackupExportError(f"staging package path already exists: {package_dir}")
    make_private_dir(package_dir, strict=True)

    try:
        (docker_cp or _docker_cp)(
            f"{container}:/backup/package/.", f"{package_dir}/"
        )
        _secure_exported_tree(package_dir)
        if not (package_dir / "backup.kkbak").is_file():
            raise BackupExportError("sealed backup package is missing")
        verified = verify_backup_package(package_dir, allow_stub=allow_stub)
        if not verified.ok:
            raise BackupExportError(
                "sealed backup package failed verification: "
                + "; ".join(verified.errors)
            )

        make_private_dir(backup, strict=True)
        destination = backup / "package"
        if destination.exists() or destination.is_symlink():
            raise BackupExportError(
                f"refusing to overwrite existing backup package: {destination}"
            )
        os.replace(package_dir, destination)
        _fsync_dir(backup)
        return destination
    except BaseException:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mail_core.backup.export",
        description="Export and verify a container-private backup package.",
    )
    parser.add_argument("--container", required=True)
    parser.add_argument("--staging-dir", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--allow-stub", action="store_true")
    args = parser.parse_args(argv)
    try:
        path = export_container_package(
            container=args.container,
            staging_dir=args.staging_dir,
            backup_dir=args.backup_dir,
            allow_stub=args.allow_stub,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        print(
            f"backup_export_failed: docker cp failed ({exc.returncode}): {detail[:500]}",
            file=sys.stderr,
        )
        return 1
    except (BackupExportError, PrivatePathError, OSError) as exc:
        print(f"backup_export_failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "package": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
