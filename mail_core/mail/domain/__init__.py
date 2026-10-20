from mail_core.mail.domain.archive import ARCHIVE_TRANSITIONS, IllegalArchiveTransition, assert_transition, can_transition
from mail_core.mail.domain.enums import (
    ArchiveState,
    FolderRole,
    JobStatus,
    JobType,
    OutboxEventType,
    ProviderType,
    RemoteOperationStatus,
    SyncPhase,
    SyncStatus,
)
from mail_core.mail.domain.models import AccountRef, FolderRef, MessageMetadata, SyncCheckpointView

__all__ = [
    "ARCHIVE_TRANSITIONS",
    "AccountRef",
    "ArchiveState",
    "FolderRef",
    "FolderRole",
    "IllegalArchiveTransition",
    "JobStatus",
    "JobType",
    "MessageMetadata",
    "OutboxEventType",
    "ProviderType",
    "RemoteOperationStatus",
    "SyncCheckpointView",
    "SyncPhase",
    "SyncStatus",
    "assert_transition",
    "can_transition",
]
