#!/usr/bin/env bash
# Pull upstream main into a sync branch and open a PR when gh is available.
set -euo pipefail
cd "$(dirname "$0")/.."

git fetch upstream main
git checkout -B upstream-sync upstream/main
git checkout main
git checkout -B sync/upstream-main main
git merge upstream/main --no-edit || {
  echo "Conflicts. Resolve, then: git push -u origin sync/upstream-main"
  exit 1
}
git push -u origin sync/upstream-main
if command -v gh >/dev/null; then
  gh pr create --base main --head sync/upstream-main --title "sync: upstream main" --body "Automated upstream sync from assast/outlookEmail." || true
fi
