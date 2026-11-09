#!/usr/bin/env bash
# Preflight schema gate for mail-core deployments.
#
# This file is meant to be sourced; sourcing it defines functions only and
# performs no checks, builds, pushes, or backups as a side effect.
#
# The gate runs the same orchestration as application startup
# (``python -m mail_core --check-migrations``): read-only judgements, zero
# writes. A non-zero exit fails the deploy before any push, build, or backup.
#
# Credentials travel exclusively via the MAIL_CORE_DATABASE_URL environment
# variable and are never printed (not even redacted) by this file.
#
# Endpoint correspondence: the database listens on postgres:5432 inside the
# Compose network; from the deploy host the same database is reachable at
# 127.0.0.1:5433 (see the postgres ports mapping in
# docker-compose.mail-core.yml). The gate runs on the host, so callers pass
# the host endpoint (127.0.0.1:5433) in MAIL_CORE_DATABASE_URL.

# Run the read-only migration check.
#   $1: repository root (used for PYTHONPATH=src resolution)
#   $2: python interpreter to run (e.g. "$repo_root/.venv/bin/python")
mail_core_preflight_check() {
    local repo_root="${1:?repo root required}"
    local python_bin="${2:?python interpreter required}"
    : "${MAIL_CORE_DATABASE_URL:?MAIL_CORE_DATABASE_URL must be set (credential via environment; never printed)}"
    PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -m mail_core --check-migrations
}
