"""MIME archive state machine (architecture §8.4)."""

from __future__ import annotations

from mail_core.mail.domain.enums import ArchiveState

# Legal transitions: from -> frozenset of to
ARCHIVE_TRANSITIONS: dict[ArchiveState, frozenset[ArchiveState]] = {
    ArchiveState.METADATA_SYNCED: frozenset({ArchiveState.ARCHIVE_PENDING}),
    ArchiveState.ARCHIVE_PENDING: frozenset(
        {
            ArchiveState.ARCHIVE_IN_PROGRESS,
            ArchiveState.ARCHIVE_PAUSED_QUOTA,
            ArchiveState.ARCHIVE_FAILED,
        }
    ),
    ArchiveState.ARCHIVE_IN_PROGRESS: frozenset(
        {
            ArchiveState.ARCHIVE_COMPLETE,
            ArchiveState.ARCHIVE_PENDING,  # retry
            ArchiveState.ARCHIVE_PAUSED_QUOTA,
            ArchiveState.ARCHIVE_FAILED,
        }
    ),
    ArchiveState.ARCHIVE_PAUSED_QUOTA: frozenset(
        {
            ArchiveState.ARCHIVE_PENDING,
            ArchiveState.ARCHIVE_FAILED,
        }
    ),
    ArchiveState.ARCHIVE_FAILED: frozenset({ArchiveState.ARCHIVE_PENDING}),
    ArchiveState.ARCHIVE_COMPLETE: frozenset(),
}


class IllegalArchiveTransition(ValueError):
    pass


def can_transition(current: ArchiveState, new: ArchiveState) -> bool:
    if current == new:
        return True
    return new in ARCHIVE_TRANSITIONS.get(current, frozenset())


def assert_transition(current: ArchiveState, new: ArchiveState) -> None:
    if not can_transition(current, new):
        raise IllegalArchiveTransition(f"{current} -> {new} is not allowed")


def apply_transition(row, new: ArchiveState) -> None:
    """Validate and apply ``row.state -> new`` (``row`` has a ``state`` str attribute).

    Every archive state write goes through here so the FSM is the single authority.
    """
    assert_transition(ArchiveState(row.state), new)
    row.state = new.value
