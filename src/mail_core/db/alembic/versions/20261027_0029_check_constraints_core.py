"""Add CHECK constraints for archive state and blob count columns.

Revision ID: 20261027_0029
Revises: 20261027_0028

A168: status/count columns had no DB-level CHECK constraints, so illegal
values could be stored and only exploded later in the application layer
as ValueError. This migration adds the minimum set (mirrored in the ORM
models):

- message_archive_state.state must be one of the ArchiveState values
- message_blobs.ref_count >= 0
- blob_quota_reservations.reserved_bytes > 0

Note: upgrade will fail on databases that already contain rows violating
these constraints; clean such rows before running it.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20261027_0029"
down_revision: Union[str, None] = "20261027_0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ARCHIVE_STATES = (
    "metadata_synced",
    "archive_pending",
    "archive_in_progress",
    "archive_paused_quota",
    "archive_failed",
    "archive_complete",
)


def upgrade() -> None:
    states_sql = ", ".join(f"'{state}'" for state in _ARCHIVE_STATES)
    op.create_check_constraint(
        "ck_message_archive_state_state_valid",
        "message_archive_state",
        f"state IN ({states_sql})",
    )
    op.create_check_constraint(
        "ck_message_blobs_ref_count_nonnegative",
        "message_blobs",
        "ref_count >= 0",
    )
    op.create_check_constraint(
        "ck_blob_quota_reservations_reserved_bytes_positive",
        "blob_quota_reservations",
        "reserved_bytes > 0",
    )


def downgrade() -> None:
    op.drop_check_constraint(
        "ck_blob_quota_reservations_reserved_bytes_positive",
        "blob_quota_reservations",
        type_="check",
    )
    op.drop_check_constraint(
        "ck_message_blobs_ref_count_nonnegative",
        "message_blobs",
        type_="check",
    )
    op.drop_check_constraint(
        "ck_message_archive_state_state_valid",
        "message_archive_state",
        type_="check",
    )
