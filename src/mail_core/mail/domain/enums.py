"""Domain enums shared across mail-core (no FastAPI / provider imports)."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class JobPriority(IntEnum):
    ON_DEMAND = 10
    DELTA = 20
    REMOTE_PUSH = 40
    METADATA = 50
    ARCHIVE_ROUTINE = 80
    RECONCILE = 90


class ProviderType(StrEnum):
    IMAP = "imap"
    GMAIL = "gmail"
    GRAPH = "graph"


class FolderRole(StrEnum):
    INBOX = "inbox"
    SENT = "sent"
    DRAFTS = "drafts"
    TRASH = "trash"
    JUNK = "junk"
    ARCHIVE = "archive"
    ALL = "all"
    OTHER = "other"


class SyncStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    AUTH_FAILED = "auth_failed"


class SyncRunStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"


class SyncPhase(StrEnum):
    FOLDER_DISCOVERY = "folder_discovery"
    METADATA = "metadata"
    INCREMENTAL_READY = "incremental_ready"
    MIME_ARCHIVE = "mime_archive"
    RECONCILE = "reconcile"


class ArchiveState(StrEnum):
    METADATA_SYNCED = "metadata_synced"
    ARCHIVE_PENDING = "archive_pending"
    ARCHIVE_IN_PROGRESS = "archive_in_progress"
    ARCHIVE_PAUSED_QUOTA = "archive_paused_quota"
    ARCHIVE_FAILED = "archive_failed"
    ARCHIVE_COMPLETE = "archive_complete"


class RemoteOperationStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class JobType(StrEnum):
    SYNC_ACCOUNT_FOLDERS = "sync_account_folders"
    SYNC_FOLDER_METADATA = "sync_folder_metadata"
    SYNC_FOLDER_DELTA = "sync_folder_delta"
    RECONCILE_FOLDER = "reconcile_folder"
    REMOTE_OPERATION_PUSH = "remote_operation_push"
    ARCHIVE_MIME_BATCH = "archive_mime_batch"
    OUTBOX_DISPATCH_WAKE = "outbox_dispatch_wake"
    GC_BLOBS = "gc_blobs"
    BACKUP_RUN = "backup_run"


class JobStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutboxEventType(StrEnum):
    ACCOUNT_UPDATED = "account.updated"
    MESSAGE_UPSERTED = "message.upserted"
    MESSAGE_REMOVED = "message.removed"
    FOLDER_STATS_UPDATED = "folder.stats_updated"
    SYNC_PROGRESS = "sync.progress"
    SYNC_REQUEST_UPDATED = "sync.request_updated"
    SYNC_COMPLETED = "sync.completed"
    SYNC_ERROR = "sync.error"
    ARCHIVE_PROGRESS = "archive.progress"
    ARCHIVE_COMPLETED = "archive.completed"
    ARCHIVE_PAUSED_QUOTA = "archive.paused_quota"
    REMOTE_OPERATION_UPDATED = "remote_operation.updated"
    CLIENT_RESYNC_HINT = "client.resync_hint"
