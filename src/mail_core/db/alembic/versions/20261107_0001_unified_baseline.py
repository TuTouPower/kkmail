"""Unified mail-core baseline migration.

Revision ID: 20261107_0001
Revises: None
Create Date: 2026-11-07
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261107_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. PostgreSQL extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 1. account_groups
    op.create_table(
        "account_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # 2. credential_secrets
    op.create_table(
        "credential_secrets",
        sa.Column("ref", sa.String(length=512), primary_key=True),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("ref"),
    )

    # 3. app_settings
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    # 4. auth_credentials
    op.create_table(
        "auth_credentials",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("login_password_hash", sa.String(length=255), nullable=True),
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # 5. accounts
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("credential_ref", sa.String(length=512), nullable=True),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("master_order", sa.Integer(), nullable=True),
        sa.Column("group_order", sa.Integer(), nullable=True),
        sa.Column("sync_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sync_status", sa.String(length=32), server_default=sa.text("'idle'"), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("recipient_addresses", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_accounts_group_id", "accounts", ["group_id"], unique=False)
    op.create_index("uq_accounts_email_lower", "accounts", [sa.text("lower(email)")], unique=True)

    # 6. account_sync_leases
    op.create_table(
        "account_sync_leases",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("account_id"),
    )

    # 7. account_sync_activity
    op.create_table(
        "account_sync_activity",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("last_foreground_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_index("ix_account_sync_activity_expires", "account_sync_activity", ["expires_at"], unique=False)

    # 8. folders
    op.create_table(
        "folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("remote_id", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=32), server_default=sa.text("'other'"), nullable=False),
        sa.Column("parent_remote_id", sa.String(length=512), nullable=True),
        sa.Column("sync_status", sa.String(length=32), server_default=sa.text("'idle'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "remote_id", name="uq_folders_account_remote"),
    )

    # 9. threads
    op.create_table(
        "threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_thread_key", sa.String(length=512), nullable=True),
        sa.Column("subject_norm", sa.String(length=998), nullable=True),
        sa.Column("sort_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "provider_thread_key", name="uq_threads_account_provider_key"),
    )

    # 10. messages
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("remote_id", sa.String(length=512), nullable=True),
        sa.Column("internet_message_id", sa.String(length=998), nullable=True),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("threads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subject", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("from_address", sa.String(length=320), server_default=sa.text("''"), nullable=False),
        sa.Column("from_name", sa.String(length=255), nullable=True),
        sa.Column("to_addresses", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("cc_addresses", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("sort_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=True),
        sa.Column("is_flagged", sa.Boolean(), nullable=True),
        sa.Column("has_attachments", sa.Boolean(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "remote_id", name="uq_messages_account_remote"),
    )
    op.create_index("ix_messages_account_sort", "messages", ["account_id", "sort_time"], unique=False)
    op.create_index("ix_messages_sort_id", "messages", ["sort_time", "id"], unique=False)
    op.create_index("ix_messages_account_internet_id", "messages", ["account_id", "internet_message_id"], unique=False)

    # 11. message_locations
    op.create_table(
        "message_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("folders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uid", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "folder_id", name="uq_message_locations"),
    )
    op.create_index("ix_message_locations_folder_id", "message_locations", ["folder_id"], unique=False)
    op.create_index("ix_message_locations_folder_message", "message_locations", ["folder_id", "message_id"], unique=False)

    # 12. message_bodies
    op.create_table(
        "message_bodies",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("text_plain", sa.Text(), nullable=True),
        sa.Column("text_html", sa.Text(), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("message_id"),
    )

    # 13. message_blobs
    op.create_table(
        "message_blobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("key_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("ref_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("gc_eligible_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_sha256", "key_version", name="uq_message_blobs_hash_key"),
        sa.CheckConstraint("ref_count >= 0", name="ck_message_blobs_ref_count_nonnegative"),
    )

    # 14. message_blob_links
    op.create_table(
        "message_blob_links",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("blob_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("message_blobs.id", ondelete="RESTRICT"), nullable=False),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index("ix_message_blob_links_blob_id", "message_blob_links", ["blob_id"], unique=False)

    # 15. attachments
    op.create_table(
        "attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("blob_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("message_blobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("part_id", sa.String(length=64), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_id", sa.String(length=255), nullable=True),
        sa.Column("is_inline", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "part_id", name="uq_attachments_message_part"),
    )
    op.create_index("ix_attachments_message_id", "attachments", ["message_id"], unique=False)

    # 16. thread_messages
    op.create_table(
        "thread_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", "message_id", name="uq_thread_messages"),
    )

    # 17. sync_checkpoints
    op.create_table(
        "sync_checkpoints",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("folders.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("cursor", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("uidvalidity", sa.BigInteger(), nullable=True),
        sa.Column("modseq", sa.BigInteger(), nullable=True),
        sa.Column("history_id", sa.String(length=128), nullable=True),
        sa.Column("delta_link", sa.Text(), nullable=True),
        sa.Column("full_scan_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("scan_generation", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fencing_token", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("account_id", "folder_id"),
    )

    # 18. sync_runs
    op.create_table(
        "sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("folders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("phase", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("fencing_token", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # 19. remote_operations
    op.create_table(
        "remote_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_key", sa.String(length=512), nullable=False),
        sa.Column("op_type", sa.String(length=64), nullable=False),
        sa.Column("desired_state", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_remote_operations_pending", "remote_operations", ["account_id", "status", "entity_key"], unique=False)
    op.create_index("ix_remote_operations_retry", "remote_operations", ["account_id", "status", "next_attempt_at"], unique=False)

    # 20. folder_stats
    op.create_table(
        "folder_stats",
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("folders.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("total_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unread_count", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("folder_id"),
    )

    # 21. folder_patrol_status
    op.create_table(
        "folder_patrol_status",
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("last_status", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_probe_failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("folder_id"),
    )

    # 22. outbox_publication_state
    op.create_table(
        "outbox_publication_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("epoch", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("next_seq", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("pruned_through_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_outbox_publication_state_singleton"),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_publication_state"),
    )
    # Initialize singleton state with default epoch
    op.execute(
        sa.text(
            """
            INSERT INTO outbox_publication_state (id, epoch, next_seq, pruned_through_seq)
            VALUES (1, gen_random_uuid(), 1, 0)
            ON CONFLICT (id) DO NOTHING
            """
        )
    )

    # 23. outbox
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("publication_seq", sa.BigInteger(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_publication_seq", "outbox", ["publication_seq"], unique=True)
    op.create_index(
        "ix_outbox_unassigned",
        "outbox",
        ["id"],
        unique=False,
        postgresql_where=sa.text("publication_seq IS NULL"),
    )

    # 24. message_archive_state
    _archive_states = (
        "metadata_synced",
        "archive_pending",
        "archive_in_progress",
        "archive_paused_quota",
        "archive_failed",
        "archive_complete",
    )
    states_sql = ", ".join(f"'{s}'" for s in _archive_states)
    op.create_table(
        "message_archive_state",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("claim_revision", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("state", sa.String(length=32), server_default=sa.text("'metadata_synced'"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("pause_reason", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("message_id"),
        sa.CheckConstraint(f"state IN ({states_sql})", name="ck_message_archive_state_state_valid"),
    )
    op.create_index(
        "ix_archive_claim",
        "message_archive_state",
        ["state", "priority"],
        unique=False,
        postgresql_where=sa.text("claimed_by IS NULL"),
    )

    # 25. worker_jobs
    op.create_table(
        "worker_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("execution_generation", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("dedupe_key", sa.String(length=128), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failure_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_generation", name="uq_worker_jobs_execution_generation"),
    )
    op.create_index("ix_worker_jobs_claim", "worker_jobs", ["status", "run_after", "priority"], unique=False)
    op.create_index(
        "ix_worker_jobs_dedupe_active",
        "worker_jobs",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL AND status IN ('pending', 'claimed')"),
    )

    # 26. message_search
    op.execute(
        """
        CREATE TABLE message_search (
            message_id UUID PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
            account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            subject TEXT NOT NULL DEFAULT '',
            from_text TEXT NOT NULL DEFAULT '',
            to_text TEXT NOT NULL DEFAULT '',
            body_text TEXT NOT NULL DEFAULT '',
            document tsvector GENERATED ALWAYS AS (
                to_tsvector('simple', coalesce(subject,'') || ' ' || coalesce(from_text,'') || ' ' || coalesce(to_text,'') || ' ' || coalesce(body_text,''))
            ) STORED,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_message_search_account ON message_search (account_id)")
    op.execute("CREATE INDEX ix_message_search_document ON message_search USING GIN (document)")
    op.execute("CREATE INDEX ix_message_search_from_trgm ON message_search USING GIN (from_text gin_trgm_ops)")
    op.execute("CREATE INDEX ix_message_search_subject_trgm ON message_search USING GIN (subject gin_trgm_ops)")
    op.create_index(
        "ix_message_search_from_text_trgm",
        "message_search",
        ["from_text"],
        postgresql_using="gin",
        postgresql_ops={"from_text": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_message_search_to_text_trgm",
        "message_search",
        ["to_text"],
        postgresql_using="gin",
        postgresql_ops={"to_text": "gin_trgm_ops"},
    )

    # 27. blob_quota_reservations
    op.create_table(
        "blob_quota_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("reserved_bytes > 0", name="ck_blob_quota_reservations_reserved_bytes_positive"),
    )
    op.create_index("ix_blob_quota_reservations_expires_at", "blob_quota_reservations", ["expires_at"], unique=False)

    # 28. sync_requests
    op.create_table(
        "sync_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_request_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_request_id"),
    )
    op.create_index("ix_sync_requests_state_created", "sync_requests", ["state", "created_at"], unique=False)

    # 29. sync_request_targets
    op.create_table(
        "sync_request_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sync_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("folders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_key", sa.String(length=255), nullable=False),
        sa.Column("requested_generation", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=32), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("safe_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "target_key", name="uq_sync_targets_request_key"),
    )
    op.create_index("ix_sync_targets_account_state", "sync_request_targets", ["account_id", "state"], unique=False)

    # 30. sync_request_target_jobs
    op.create_table(
        "sync_request_target_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sync_request_targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("execution_generation", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("worker_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("phase", sa.String(length=64), server_default=sa.text("'sync'"), nullable=False),
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("safe_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_id", "execution_generation", name="uq_sync_target_jobs_target_generation"),
    )
    op.create_index("ix_sync_target_jobs_job", "sync_request_target_jobs", ["job_id"], unique=False)
    op.create_index("ix_sync_target_jobs_generation", "sync_request_target_jobs", ["execution_generation"], unique=False)

    # 31. message_remote_image_allows
    op.create_table(
        "message_remote_image_allows",
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )

    # 32. sender_remote_image_allows
    op.create_table(
        "sender_remote_image_allows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_address", name="uq_sender_remote_image_allows_from_address"),
    )


def downgrade() -> None:
    op.drop_table("sender_remote_image_allows")
    op.drop_table("message_remote_image_allows")
    op.drop_table("sync_request_target_jobs")
    op.drop_table("sync_request_targets")
    op.drop_table("sync_requests")
    op.drop_table("blob_quota_reservations")
    op.execute("DROP TABLE IF EXISTS message_search")
    op.drop_table("worker_jobs")
    op.drop_table("message_archive_state")
    op.drop_table("outbox")
    op.drop_table("outbox_publication_state")
    op.drop_table("folder_patrol_status")
    op.drop_table("folder_stats")
    op.drop_table("remote_operations")
    op.drop_table("sync_runs")
    op.drop_table("sync_checkpoints")
    op.drop_table("thread_messages")
    op.drop_table("attachments")
    op.drop_table("message_blob_links")
    op.drop_table("message_blobs")
    op.drop_table("message_bodies")
    op.drop_table("message_locations")
    op.drop_table("messages")
    op.drop_table("threads")
    op.drop_table("folders")
    op.drop_table("account_sync_activity")
    op.drop_table("account_sync_leases")
    op.drop_table("accounts")
    op.drop_table("auth_credentials")
    op.drop_table("app_settings")
    op.drop_table("credential_secrets")
    op.drop_table("account_groups")
