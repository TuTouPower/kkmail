from types import SimpleNamespace

import pytest

from mail_core.mail.domain.archive import apply_transition
from mail_core.mail.domain import (
    ArchiveState,
    IllegalArchiveTransition,
    assert_transition,
    can_transition,
)


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


@pytest.mark.parametrize("state", list(ArchiveState))
def test_same_state_is_not_an_implicit_transition(state):
    assert not can_transition(state, state)
    with pytest.raises(IllegalArchiveTransition):
        assert_transition(state, state)


def test_cannot_skip_to_complete():
    assert not can_transition(ArchiveState.METADATA_SYNCED, ArchiveState.ARCHIVE_COMPLETE)


def test_apply_transition_rejects_unknown_stored_state_with_domain_error():
    row = SimpleNamespace(state="corrupt-archive-state")

    with pytest.raises(IllegalArchiveTransition, match="unknown archive state 'corrupt-archive-state'"):
        apply_transition(row, ArchiveState.ARCHIVE_PENDING)
