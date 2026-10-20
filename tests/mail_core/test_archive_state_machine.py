import pytest

from mail_core.mail.domain import ArchiveState, IllegalArchiveTransition, assert_transition, can_transition


def test_happy_path():
    assert can_transition(ArchiveState.METADATA_SYNCED, ArchiveState.ARCHIVE_PENDING)
    assert can_transition(ArchiveState.ARCHIVE_PENDING, ArchiveState.ARCHIVE_IN_PROGRESS)
    assert can_transition(ArchiveState.ARCHIVE_IN_PROGRESS, ArchiveState.ARCHIVE_COMPLETE)


def test_quota_pause_and_resume():
    assert can_transition(ArchiveState.ARCHIVE_PENDING, ArchiveState.ARCHIVE_PAUSED_QUOTA)
    assert can_transition(ArchiveState.ARCHIVE_PAUSED_QUOTA, ArchiveState.ARCHIVE_PENDING)


def test_complete_is_terminal():
    assert not can_transition(ArchiveState.ARCHIVE_COMPLETE, ArchiveState.ARCHIVE_PENDING)
    with pytest.raises(IllegalArchiveTransition):
        assert_transition(ArchiveState.ARCHIVE_COMPLETE, ArchiveState.METADATA_SYNCED)


def test_cannot_skip_to_complete():
    assert not can_transition(ArchiveState.METADATA_SYNCED, ArchiveState.ARCHIVE_COMPLETE)
