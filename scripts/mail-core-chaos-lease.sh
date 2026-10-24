#!/usr/bin/env bash
# Chaos smoke: lease steal + stale job reclaim after simulated worker kill.
# The shared runner creates and verifies an owned loopback-only test database before migration.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

exec "$ROOT/scripts/run-mail-core-tests.sh" run -k \
  'test_worker_kill_allows_lease_steal_and_rejects_stale_fencing or test_stale_claimed_job_reclaimed_after_worker_death or test_skip_locked_claim_exclusive or test_fencing_rejects_stale_checkpoint_commit or test_lease_busy_while_held'
