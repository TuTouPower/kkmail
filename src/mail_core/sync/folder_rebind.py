"""1-to-1 localized system-folder rebinding and IMAP path rewrite helpers (t092)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import FolderRemoteState, RemoteOperationStatus
from mail_core.mail.domain.folder_views import CONTAINER, REBINDABLE_SYSTEM_ROLES, VIEW, is_gmail_view
from mail_core.mail.storage.models import Folder, Message, RemoteOperation
from mail_core.providers.imap import _IMAP_REMOTE_SEP, format_imap_remote_id, parse_imap_remote_id

_REMOTE_OP_FOLDER_KEYS = (
    "folder_remote_id",
    "trash_folder_remote_id",
    "dest_folder_remote_id",
    "to_folder",
)


def expected_folder_kind(rf, *, is_gmail: bool) -> str:
    """Return expected persisted kind ('view' or 'container') for a discovered remote folder."""
    return VIEW if (is_gmail and is_gmail_view(rf.role, rf.remote_id)) else CONTAINER


def _collect_rebind_candidates(
    missing_existing: list[Folder],
    *,
    is_gmail: bool,
) -> tuple[dict[tuple[str, str], list[Folder]], dict[tuple[str, str], list[Folder]]]:
    active_missing: dict[tuple[str, str], list[Folder]] = {}
    legacy_missing: dict[tuple[str, str], list[Folder]] = {}
    for folder in missing_existing:
        if not folder.selectable or folder.role not in REBINDABLE_SYSTEM_ROLES:
            continue
        key = (folder.kind, folder.role)
        if folder.remote_state == FolderRemoteState.ACTIVE.value:
            active_missing.setdefault(key, []).append(folder)
        elif is_gmail:
            legacy_missing.setdefault(key, []).append(folder)
    return active_missing, legacy_missing


def find_system_rebind_pairs(
    unmatched_remotes: list,
    missing_existing: list[Folder],
    *,
    is_gmail: bool,
) -> list[tuple[object, Folder]]:
    """Match 1-to-1 vanished system folders to newly localized remote paths.

    Prefers newly vanished ``active`` folders over historical ``missing`` Gmail
    candidates so a pre-existing stale ``missing`` row never blocks rebinding
    the currently active localized folder.
    """
    remote_buckets: dict[tuple[str, str], list] = {}
    for rf in unmatched_remotes:
        if rf.selectable and rf.role in REBINDABLE_SYSTEM_ROLES:
            remote_buckets.setdefault((expected_folder_kind(rf, is_gmail=is_gmail), rf.role), []).append(rf)

    active_missing, legacy_missing = _collect_rebind_candidates(missing_existing, is_gmail=is_gmail)

    pairs: list[tuple[object, Folder]] = []
    for key, remotes in remote_buckets.items():
        if len(remotes) != 1:
            continue
        active_candidates = active_missing.get(key) or []
        candidates = (
            active_candidates
            if active_candidates or not is_gmail
            else (legacy_missing.get(key) or [])
        )
        if len(candidates) == 1:
            pairs.append((remotes[0], candidates[0]))
    return pairs


def rebind_system_folders(
    session: Session,
    *,
    account_id: uuid.UUID,
    sorted_remote_folders: list,
    by_remote: dict[str, Folder],
    remote_ids: set[str],
    is_gmail: bool,
    apply_folder_attributes,
) -> dict[str, Folder]:
    """Rebind vanished system folders 1-to-1 before new folder creation."""
    unmatched_remotes = [rf for rf in sorted_remote_folders if rf.remote_id not in by_remote]
    missing_existing = [folder for rid, folder in by_remote.items() if rid not in remote_ids]
    rebound: dict[str, Folder] = {}
    for rf, existing in find_system_rebind_pairs(unmatched_remotes, missing_existing, is_gmail=is_gmail):
        old_remote_id = existing.remote_id
        expected_kind = expected_folder_kind(rf, is_gmail=is_gmail)
        by_remote.pop(old_remote_id, None)
        apply_folder_attributes(existing, rf, expected_kind=expected_kind)
        if existing.kind == CONTAINER and old_remote_id != rf.remote_id:
            rebind_folder_message_paths(
                session,
                account_id=account_id,
                old_remote_id=old_remote_id,
                new_remote_id=rf.remote_id,
            )
        by_remote[rf.remote_id] = existing
        rebound[rf.remote_id] = existing
    if rebound:
        session.flush()
    return rebound


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _decrement_orphan_blob_refs(session: Session, blob_counts: dict[uuid.UUID, int]) -> None:
    for blob_id, dec in blob_counts.items():
        if dec <= 0:
            continue
        session.execute(
            sa.text(
                """
                UPDATE message_blobs
                   SET ref_count = GREATEST(0, ref_count - :dec),
                       gc_eligible_at = CASE
                           WHEN GREATEST(0, ref_count - :dec) = 0 THEN COALESCE(gc_eligible_at, now())
                           ELSE gc_eligible_at
                       END
                 WHERE id = :bid
                """
            ),
            {"bid": blob_id, "dec": dec},
        )


def _merge_duplicate_message_rows(
    session: Session,
    *,
    dup_msg_id: uuid.UUID,
    surv_msg_id: uuid.UUID,
) -> None:
    """Merge foreign-key dependents of a duplicate Message row into survivor before deleting dup."""
    params = {"dup": dup_msg_id, "surv": surv_msg_id}
    dup_locs = session.execute(
        sa.text("SELECT folder_id, uid FROM message_locations WHERE message_id = :dup"),
        {"dup": dup_msg_id},
    ).all()
    for folder_id, uid in dup_locs:
        session.execute(
            sa.text(
                """
                INSERT INTO message_locations (id, message_id, folder_id, uid)
                VALUES (:id, :surv, :fid, :uid)
                ON CONFLICT (message_id, folder_id) DO NOTHING
                """
            ),
            {"id": uuid.uuid4(), "surv": surv_msg_id, "fid": folder_id, "uid": uid},
        )
    session.execute(sa.text("DELETE FROM message_locations WHERE message_id = :dup"), {"dup": dup_msg_id})

    has_surv_body = session.execute(
        sa.text("SELECT 1 FROM message_bodies WHERE message_id = :surv LIMIT 1"), {"surv": surv_msg_id}
    ).first()
    if has_surv_body is None:
        session.execute(sa.text("UPDATE message_bodies SET message_id = :surv WHERE message_id = :dup"), params)
    else:
        session.execute(sa.text("DELETE FROM message_bodies WHERE message_id = :dup"), {"dup": dup_msg_id})

    surv_arch = session.execute(
        sa.text("SELECT state FROM message_archive_state WHERE message_id = :surv"), {"surv": surv_msg_id}
    ).scalar_one_or_none()
    dup_arch = session.execute(
        sa.text("SELECT state FROM message_archive_state WHERE message_id = :dup"), {"dup": dup_msg_id}
    ).scalar_one_or_none()
    if dup_arch is not None:
        if surv_arch is None:
            session.execute(sa.text("UPDATE message_archive_state SET message_id = :surv WHERE message_id = :dup"), params)
        elif surv_arch != "archive_complete" and dup_arch == "archive_complete":
            session.execute(sa.text("DELETE FROM message_archive_state WHERE message_id = :surv"), {"surv": surv_msg_id})
            session.execute(sa.text("UPDATE message_archive_state SET message_id = :surv WHERE message_id = :dup"), params)
        else:
            session.execute(sa.text("DELETE FROM message_archive_state WHERE message_id = :dup"), {"dup": dup_msg_id})

    dropped_blobs: dict[uuid.UUID, int] = {}
    surv_blob = session.execute(
        sa.text("SELECT blob_id FROM message_blob_links WHERE message_id = :surv"), {"surv": surv_msg_id}
    ).scalar_one_or_none()
    dup_blob = session.execute(
        sa.text("SELECT blob_id FROM message_blob_links WHERE message_id = :dup"), {"dup": dup_msg_id}
    ).scalar_one_or_none()
    if dup_blob is not None:
        if surv_blob is None:
            session.execute(sa.text("UPDATE message_blob_links SET message_id = :surv WHERE message_id = :dup"), params)
        else:
            session.execute(sa.text("DELETE FROM message_blob_links WHERE message_id = :dup"), {"dup": dup_msg_id})
            dropped_blobs[dup_blob] = dropped_blobs.get(dup_blob, 0) + 1

    has_surv_att = session.execute(
        sa.text("SELECT 1 FROM attachments WHERE message_id = :surv LIMIT 1"), {"surv": surv_msg_id}
    ).first()
    if has_surv_att is None:
        session.execute(sa.text("UPDATE attachments SET message_id = :surv WHERE message_id = :dup"), params)
    else:
        att_blobs = session.execute(
            sa.text("SELECT blob_id, COUNT(*) FROM attachments WHERE message_id = :dup AND blob_id IS NOT NULL GROUP BY blob_id"),
            {"dup": dup_msg_id},
        ).all()
        for bid, cnt in att_blobs:
            dropped_blobs[bid] = dropped_blobs.get(bid, 0) + int(cnt)
        session.execute(sa.text("DELETE FROM attachments WHERE message_id = :dup"), {"dup": dup_msg_id})

    _decrement_orphan_blob_refs(session, dropped_blobs)

    session.execute(
        sa.text(
            """
            UPDATE thread_messages tm
               SET message_id = :surv
             WHERE tm.message_id = :dup
               AND NOT EXISTS (
                   SELECT 1 FROM thread_messages existing
                    WHERE existing.thread_id = tm.thread_id AND existing.message_id = :surv
               )
            """
        ),
        params,
    )
    session.execute(sa.text("DELETE FROM thread_messages WHERE message_id = :dup"), {"dup": dup_msg_id})

    has_surv_search = session.execute(
        sa.text("SELECT 1 FROM message_search WHERE message_id = :surv LIMIT 1"), {"surv": surv_msg_id}
    ).first()
    if has_surv_search is None:
        session.execute(sa.text("UPDATE message_search SET message_id = :surv WHERE message_id = :dup"), params)
    else:
        session.execute(sa.text("DELETE FROM message_search WHERE message_id = :dup"), {"dup": dup_msg_id})

    session.execute(sa.text("UPDATE blob_quota_reservations SET message_id = :surv WHERE message_id = :dup"), params)
    session.execute(
        sa.text(
            """
            INSERT INTO message_remote_image_allows (message_id, created_at)
            SELECT :surv, created_at FROM message_remote_image_allows WHERE message_id = :dup
            ON CONFLICT (message_id) DO NOTHING
            """
        ),
        params,
    )
    session.execute(sa.text("DELETE FROM message_remote_image_allows WHERE message_id = :dup"), {"dup": dup_msg_id})
    session.execute(sa.text("DELETE FROM messages WHERE id = :dup"), {"dup": dup_msg_id})


def _rewrite_remote_ops_for_path_rebind(
    session: Session,
    *,
    account_id: uuid.UUID,
    old_remote_id: str,
    new_remote_id: str,
    safe_old: str,
    remapped_msg_rids: dict[str, str],
) -> None:
    pending_ops = list(
        session.scalars(
            select(RemoteOperation).where(
                RemoteOperation.account_id == account_id,
                RemoteOperation.status != RemoteOperationStatus.DONE.value,
            )
        ).all()
    )
    for op in pending_ops:
        desired = dict(op.desired_state or {})
        changed = False
        msg_rid = desired.get("remote_id")
        if isinstance(msg_rid, str):
            new_msg_rid = remapped_msg_rids.get(msg_rid)
            if new_msg_rid is None:
                parsed = parse_imap_remote_id(msg_rid)
                if parsed is not None and parsed[1] == safe_old:
                    new_msg_rid = format_imap_remote_id(new_remote_id, parsed[0], parsed[2])
            if new_msg_rid is not None and new_msg_rid != msg_rid:
                desired["remote_id"] = new_msg_rid
                changed = True
                old_prefix = f"msg:{msg_rid}:"
                if op.entity_key.startswith(old_prefix):
                    op.entity_key = f"msg:{new_msg_rid}:{op.entity_key[len(old_prefix):]}"
        for key in _REMOTE_OP_FOLDER_KEYS:
            if desired.get(key) == old_remote_id:
                desired[key] = new_remote_id
                changed = True
        if changed:
            op.desired_state = desired


def rebind_folder_message_paths(
    session: Session,
    *,
    account_id: uuid.UUID,
    old_remote_id: str,
    new_remote_id: str,
) -> None:
    """Rewrite embedded folder path inside IMAP Message.remote_id and open RemoteOperations."""
    if not old_remote_id or old_remote_id == new_remote_id:
        return
    safe_old = old_remote_id.replace(_IMAP_REMOTE_SEP, " ")
    pattern = f"%{_IMAP_REMOTE_SEP}{_escape_like(safe_old)}{_IMAP_REMOTE_SEP}%"
    candidates = list(
        session.scalars(
            select(Message).where(
                Message.account_id == account_id,
                Message.remote_id.like(pattern, escape="\\"),
            )
        ).all()
    )

    matched: list[tuple[Message, str]] = []
    remapped_msg_rids: dict[str, str] = {}
    for msg in candidates:
        parsed = parse_imap_remote_id(msg.remote_id)
        if parsed is None or parsed[1] != safe_old:
            continue
        new_msg_rid = format_imap_remote_id(new_remote_id, parsed[0], parsed[2])
        matched.append((msg, new_msg_rid))
        remapped_msg_rids[msg.remote_id] = new_msg_rid

    if matched:
        target_rids = {new_rid for _msg, new_rid in matched}
        existing_targets = {
            row.remote_id: row.id
            for row in session.scalars(
                select(Message).where(
                    Message.account_id == account_id,
                    Message.remote_id.in_(target_rids),
                )
            ).all()
        }
        for msg, new_msg_rid in matched:
            surv_id = existing_targets.get(new_msg_rid)
            if surv_id is not None and surv_id != msg.id:
                _merge_duplicate_message_rows(session, dup_msg_id=msg.id, surv_msg_id=surv_id)
                session.flush()
            else:
                msg.remote_id = new_msg_rid
                existing_targets[new_msg_rid] = msg.id
        session.flush()

    _rewrite_remote_ops_for_path_rebind(
        session,
        account_id=account_id,
        old_remote_id=old_remote_id,
        new_remote_id=new_remote_id,
        safe_old=safe_old,
        remapped_msg_rids=remapped_msg_rids,
    )
    session.flush()
