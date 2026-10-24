"""The chaos wrapper must use the shared test runner without installing dependencies."""

import os
from pathlib import Path
import subprocess


def test_chaos_wrapper_delegates_without_runtime_installs(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    fake_bin = tmp_path / "bin"
    scripts.mkdir()
    fake_bin.mkdir()

    source_root = Path(__file__).resolve().parents[2]
    wrapper = scripts / "mail-core-chaos-lease.sh"
    wrapper.write_text((source_root / "scripts/mail-core-chaos-lease.sh").read_text())

    captured_args = tmp_path / "runner-args"
    runner = scripts / "run-mail-core-tests.sh"
    runner.write_text('#!/bin/bash\nprintf \'%s\\n\' "$@" > "$CAPTURE_FILE"\n')
    runner.chmod(0o755)

    installer_marker = tmp_path / "installer-called"
    for command in ("pip", "pip3", "python", "python3", "uv"):
        stub = fake_bin / command
        stub.write_text('#!/bin/bash\nprintf \'%s\\n\' "$0" >> "$INSTALL_MARKER"\n')
        stub.chmod(0o755)

    env = os.environ.copy()
    env.update(
        PATH=f"{fake_bin}:/bin:/usr/bin",
        CAPTURE_FILE=str(captured_args),
        INSTALL_MARKER=str(installer_marker),
    )
    result = subprocess.run(
        ["/bin/bash", str(wrapper)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert captured_args.read_text().splitlines() == [
        "run",
        "-k",
        "test_worker_kill_allows_lease_steal_and_rejects_stale_fencing or "
        "test_stale_claimed_job_reclaimed_after_worker_death or "
        "test_skip_locked_claim_exclusive or test_fencing_rejects_stale_checkpoint_commit or "
        "test_lease_busy_while_held",
    ]
    assert not installer_marker.exists()
