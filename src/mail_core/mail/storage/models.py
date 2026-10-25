"""SQLAlchemy ORM models for mail-core (architecture §10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mail_core.db.base import Base
from mail_core.mail.domain.enums import SyncStatus


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class AccountGroup(Base):
    """Sidebar account groups (minimal)."""

    __tablename__ = "account_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    color: Mapped[Optional[str]] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CredentialSecret(Base):
    """Provider credentials (OAuth tokens / IMAP passwords), AES-GCM encrypted at rest.

    Key = HKDF(blob key[key_version], info="kkmail/credential-store/v1"); AAD = ref.
    """

    __tablename__ = "credential_secrets"

    ref: Mapped[str] = mapped_column(String(512), primary_key=True)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AppSetting(Base):
    """Non-secret app settings (never store passwords/tokens here)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuthCredential(Base):
    """System authentication credential store (Plan A)."""

    __tablename__ = "auth_credentials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    login_password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    session_epoch: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        Index("ix_accounts_group_id", "group_id"),
        Index("uq_accounts_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    # Opaque reference into OS Keychain / KMS — never store raw secrets here.
    credential_ref: Mapped[Optional[str]] = mapped_column(String(512))
    group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account_groups.id", ondelete="SET NULL")
    )
    master_order: Mapped[Optional[int]] = mapped_column(Integer)
    group_order: Mapped[Optional[int]] = mapped_column(Integer)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sync_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text(f"'{SyncStatus.IDLE.value}'")
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Folder(Base):
    __tablename__ = "folders"
    __table_args__ = (UniqueConstraint("account_id", "remote_id", name="uq_folders_account_remote"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    remote_id: Mapped[str] = mapped_column(String(512), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'other'"))
    parent_remote_id: Mapped[Optional[str]] = mapped_column(String(512))
    sync_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text(f"'{SyncStatus.IDLE.value}'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Thread(Base):
    __tablename__ = "threads"
    __table_args__ = (UniqueConstraint("account_id", "provider_thread_key", name="uq_threads_account_provider_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    provider_thread_key: Mapped[Optional[str]] = mapped_column(String(512))
    subject_norm: Mapped[Optional[str]] = mapped_column(String(998))
    sort_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("account_id", "remote_id", name="uq_messages_account_remote"),
        Index("ix_messages_account_sort", "account_id", "sort_time"),
        # Inbox/folder keyset: ORDER BY sort_time DESC, id DESC (queries.list_messages_keyset).
        Index("ix_messages_sort_id", "sort_time", "id"),
        Index("ix_messages_account_internet_id", "account_id", "internet_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    # Null marks a local retained message whose canonical provider identity is unknown.
    remote_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    internet_message_id: Mapped[Optional[str]] = mapped_column(String(998))
    thread_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="SET NULL"))
    subject: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    from_address: Mapped[str] = mapped_column(String(320), nullable=False, server_default=text("''"))
    from_name: Mapped[Optional[str]] = mapped_column(String(255))
    to_addresses: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    cc_addresses: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    sort_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_read: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_flagged: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_attachments: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    snippet: Mapped[Optional[str]] = mapped_column(Text)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MessageLocation(Base):
    __tablename__ = "message_locations"
    __table_args__ = (
        UniqueConstraint("message_id", "folder_id", name="uq_message_locations"),
        Index("ix_message_locations_folder_id", "folder_id"),
        # Supports folder_id IN (...) join into messages for keyset inbox lists.
        Index("ix_message_locations_folder_message", "folder_id", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    folder_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), nullable=False)
    uid: Mapped[Optional[int]] = mapped_column(BigInteger)


class MessageBody(Base):
    """Parsed text/HTML references — not authoritative (MIME blob is)."""

    __tablename__ = "message_bodies"

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    text_plain: Mapped[Optional[str]] = mapped_column(Text)
    text_html: Mapped[Optional[str]] = mapped_column(Text)
    parse_error: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MessageBlob(Base):
    __tablename__ = "message_blobs"
    __table_args__ = (UniqueConstraint("content_sha256", "key_version", name="uq_message_blobs_hash_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Relative path under blob root; never expose as user-controlled API path.
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    ref_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    # Set when ref_count hits 0; GC cool-off is measured from this, not created_at.
    gc_eligible_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MessageBlobLink(Base):
    """Binds a message to its authoritative MIME blob once archive_complete."""

    __tablename__ = "message_blob_links"
    __table_args__ = (Index("ix_message_blob_links_blob_id", "blob_id"),)

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    blob_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("message_blobs.id", ondelete="RESTRICT"), nullable=False)


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_attachments_message_id", "message_id"),
        UniqueConstraint("message_id", "part_id", name="uq_attachments_message_part"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    blob_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("message_blobs.id", ondelete="SET NULL"))
    part_id: Mapped[Optional[str]] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(255))
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    content_id: Mapped[Optional[str]] = mapped_column(String(255))
    is_inline: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class ThreadMessage(Base):
    __tablename__ = "thread_messages"
    __table_args__ = (UniqueConstraint("thread_id", "message_id", name="uq_thread_messages"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class SyncCheckpoint(Base):
    __tablename__ = "sync_checkpoints"

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    folder_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), primary_key=True)
    cursor: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    uidvalidity: Mapped[Optional[int]] = mapped_column(BigInteger)
    modseq: Mapped[Optional[int]] = mapped_column(BigInteger)
    history_id: Mapped[Optional[str]] = mapped_column(String(128))
    delta_link: Mapped[Optional[str]] = mapped_column(Text)
    full_scan_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Last fencing token that successfully committed this checkpoint.
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"))
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error: Mapped[Optional[str]] = mapped_column(Text)
    fencing_token: Mapped[Optional[int]] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RemoteOperation(Base):
    __tablename__ = "remote_operations"
    __table_args__ = (Index("ix_remote_operations_pending", "account_id", "status", "entity_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(512), nullable=False)
    op_type: Mapped[str] = mapped_column(String(64), nullable=False)
    desired_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FolderStats(Base):
    __tablename__ = "folder_stats"

    folder_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), primary_key=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    unread_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AccountSyncLease(Base):
    """Account-level sync lease + fencing token (architecture §7.5)."""

    __tablename__ = "account_sync_leases"

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))


class OutboxPublicationState(Base):
    """Singleton tracking outbox stream epoch and monotonically increasing publication sequence."""

    __tablename__ = "outbox_publication_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_outbox_publication_state_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    epoch: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=_uuid)
    next_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class OutboxEvent(Base):
    """Transactional outbox row (architecture §13.2)."""

    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_outbox_undispatched", "dispatched_at", "id"),
        Index("ix_outbox_publication_seq", "publication_seq", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    publication_seq: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class MessageArchiveState(Base):
    """Per-message MIME archive state machine (architecture §8.4)."""

    __tablename__ = "message_archive_state"
    __table_args__ = (
        Index("ix_archive_claim", "state", "priority", postgresql_where=text("claimed_by IS NULL")),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'metadata_synced'"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("2"))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    pause_reason: Mapped[Optional[str]] = mapped_column(String(255))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    claimed_by: Mapped[Optional[str]] = mapped_column(String(128))
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkerJob(Base):
    """PostgreSQL task table — claimed with FOR UPDATE SKIP LOCKED."""

    __tablename__ = "worker_jobs"
    __table_args__ = (
        Index("ix_worker_jobs_claim", "status", "run_after", "priority"),
        Index("ix_worker_jobs_dedupe_active", "dedupe_key", unique=True, postgresql_where=text("dedupe_key IS NOT NULL AND status IN ('pending', 'claimed')")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"))
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'pending'"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Claim count, including claims reclaimed after worker interruption.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failure_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_by: Mapped[Optional[str]] = mapped_column(String(128))
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MessageSearch(Base):
    """FTS projection — searchable fields are not field-encrypted (architecture §11.2)."""

    __tablename__ = "message_search"
    __table_args__ = (
        Index("ix_message_search_from_text_trgm", "from_text", postgresql_using="gin", postgresql_ops={"from_text": "gin_trgm_ops"}),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    from_text: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    body_text: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BlobQuotaReservation(Base):
    """Temporary reservation of blob disk quota before physical write completes."""

    __tablename__ = "blob_quota_reservations"
    __table_args__ = (Index("ix_blob_quota_reservations_expires_at", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    message_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"))
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SyncRequest(Base):
    """Scoped synchronization request tracking delta or full progress (D10)."""

    __tablename__ = "sync_requests"
    __table_args__ = (Index("ix_sync_requests_state_created", "state", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    client_request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'queued'"))
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SyncRequestTarget(Base):
    """Individual target execution tracking within a sync request (D10)."""

    __tablename__ = "sync_request_targets"
    __table_args__ = (
        UniqueConstraint("request_id", "target_key", name="uq_sync_targets_request_key"),
        Index("ix_sync_targets_account_state", "account_id", "state"),
        Index("ix_sync_targets_job_id", "current_job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sync_requests.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"))
    folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"))
    current_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("worker_jobs.id", ondelete="SET NULL"))
    target_key: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_generation: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'queued'"))
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    safe_error: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AccountSyncActivity(Base):
    """Tracks account foreground activity for cold/hot sync scheduling (D10)."""

    __tablename__ = "account_sync_activity"
    __table_args__ = (Index("ix_account_sync_activity_expires", "expires_at"),)

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    last_foreground_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

