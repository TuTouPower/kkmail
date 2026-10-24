from __future__ import annotations

import base64
import os
from pathlib import Path
import subprocess


def test_backup_restore_drill_refuses_shared_keys_before_deleting_output(tmp_path):
    root = Path(__file__).resolve().parents[2]
    output_dir = tmp_path / "kkmail-backup-drill-a77"
    output_dir.mkdir()
    sentinel = output_dir / "preserve.txt"
    sentinel.write_text("keep", encoding="utf-8")
    shared_key = base64.b64encode(os.urandom(32)).decode("ascii")
    env = os.environ.copy()
    env["MAIL_CORE_BACKUP_KEY"] = shared_key
    env["MAIL_CORE_BLOB_KEY_V1"] = shared_key
    for name in (
        "MAIL_CORE_BACKUP_KEYS",
        "MAIL_CORE_BLOB_KEYS",
        "MAIL_CORE_BACKUP_KEY_VERSION",
        "MAIL_CORE_BLOB_KEY_VERSION",
        "MAIL_CORE_BLOB_ACTIVE_VERSION",
    ):
        env.pop(name, None)

    result = subprocess.run(
        ["bash", str(root / "scripts/mail-core-backup-restore-drill.sh"), str(output_dir)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 2
    assert "MAIL_CORE_BACKUP_KEY must differ from MAIL_CORE_BLOB_KEY_V1" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"
