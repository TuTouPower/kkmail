"""t079 guard (AC-003): MAIL_CORE_COOKIE_SECURE must not survive anywhere
in the live configuration surface.

The scan is a reverse enumeration (t079_code_f002): the whole worktree is
scanned and only known non-live areas are excluded, so a future file --
a new compose file at the root, a deploy script under scripts/, a config
under config/, a new doc tree -- that reintroduces the variable fails
here instead of slipping past an enumerated allowlist of places to look.

Excluded as archives / non-live, mirroring the sensitive-scan boundary
in docs/blueprint/testing.md plus the toolchain itself:
- docs/reviews, docs/archive, docs/tasks, docs/pending, docs/findings,
  docs/spikes, docs/handoff.md: reviewed-in records that legitimately
  quote the removed variable (A98 history, the p078 report, this task).
- docs/blueprint/decisions: the decision archive; the 20261113 record
  must name the variable it removed.
- tests: the scheme tests deliberately set the variable to prove it is
  ignored, and this guard holds the needle constant itself.
- .repo_template: the synced toolchain, not this app's configuration.
- VCS / environment / build dirs (.git, .venv, .scratch, node_modules,
  dist, __pycache__).

Symlinks are followed only while their target stays inside the worktree
(t079_code_f003): this worktree's root .env links to the main checkout's
deployment .env, which is not part of this repo -- its content must never
fail (or pass) this guard. In-tree links such as .env.example ->
config/.env.example remain scanned.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEEDLE = "MAIL_CORE_COOKIE_SECURE"

PRUNE_DIRS = {
    ".git",
    ".venv",
    ".scratch",
    ".repo_template",
    "node_modules",
    "dist",
    "__pycache__",
}
EXCLUDE_PREFIXES = (
    "tests",
    "docs/reviews",
    "docs/archive",
    "docs/tasks",
    "docs/pending",
    "docs/findings",
    "docs/spikes",
    "docs/blueprint/decisions",
)
EXCLUDE_FILES = {"docs/handoff.md"}


def _iter_live_files():
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in PRUNE_DIRS for part in rel.parts):
            continue
        rel_posix = rel.as_posix()
        if rel_posix in EXCLUDE_FILES:
            continue
        if any(
            rel_posix == prefix or rel_posix.startswith(prefix + "/")
            for prefix in EXCLUDE_PREFIXES
        ):
            continue
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not resolved.is_relative_to(ROOT):
            # Out-of-tree symlink target (e.g. the deployment .env of
            # another checkout): not this repo's live surface.
            continue
        yield path


def _collect_offenders() -> list[str]:
    offenders = []
    for path in _iter_live_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if NEEDLE in text:
            offenders.append(str(path.relative_to(ROOT)))
    return offenders


def test_cookie_secure_env_removed_from_live_surface():
    assert _collect_offenders() == []


def test_cookie_secure_guard_ignores_out_of_tree_symlink(tmp_path):
    outside = tmp_path / "outside_probe.txt"
    outside.write_text(f"{NEEDLE}=1\n", encoding="utf-8")
    link = ROOT / "__t079_outside_link_probe__"
    try:
        os.symlink(outside, link)
        assert "__t079_outside_link_probe__" not in _collect_offenders()
    finally:
        link.unlink(missing_ok=True)
