"""Replace overloaded folders.sync_status with selectable/remote_state and coalesce duplicate system folders.

Revises: 20261125_0006
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "20261126_0007"
down_revision = "20261125_0006"
branch_labels = None
depends_on = None

_GMAIL_IMPORTANT_IDS = ("[Gmail]/Important", "[Gmail]/重要", "[Gmail]/&kc2JgQ-")
_GMAIL_ALL_IDS = ("[Gmail]/All Mail", "[Gmail]/所有邮件", "[Gmail]/&YkBnCZCuTvY-")
_GMAIL_SYSTEM_ROLES = (
    "all",
    "important",
    "sent",
    "drafts",
    "trash",
    "junk",
    "flagged",
    "archive",
)
_GMAIL_ACCOUNT_PREDICATE = (
    "lower(a.email) LIKE '%@gmail.com' "
    "OR lower(a.email) LIKE '%@googlemail.com' "
    "OR lower(COALESCE(a.config ->> 'imap_host', '')) LIKE '%gmail%'"
)


_IMAP_REMOTE_SEP = "\x1f"
_REMOTE_OP_FOLDER_KEYS = (
    "folder_remote_id",
    "trash_folder_remote_id",
    "dest_folder_remote_id",
    "to_folder",
)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_imap_remote_id(remote_id: str) -> tuple[int, str, int] | None:
    parts = remote_id.split(_IMAP_REMOTE_SEP)
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), parts[1], int(parts[2])
    except ValueError:
        return None


def _format_imap_remote_id(folder: str, uidvalidity: int, uid: int) -> str:
    safe_folder = folder.replace(_IMAP_REMOTE_SEP, " ")
    return f"{int(uidvalidity)}{_IMAP_REMOTE_SEP}{safe_folder}{_IMAP_REMOTE_SEP}{int(uid)}"


def _merge_duplicate_message_sql(
    conn: sa.Connection,
    *,
    dup_msg_id: uuid.UUID,
    surv_msg_id: uuid.UUID,
) -> None:
    params = {"dup": dup_msg_id, "surv": surv_msg_id}
    dup_locs = conn.execute(
        sa.text("SELECT folder_id, uid FROM message_locations WHERE message_id = :dup"),
        {"dup": dup_msg_id},
    ).all()
    for folder_id, uid in dup_locs:
        conn.execute(
            sa.text(
                """
                INSERT INTO message_locations (id, message_id, folder_id, uid)
                VALUES (:id, :surv, :fid, :uid)
                ON CONFLICT (message_id, folder_id) DO NOTHING
                """
            ),
            {"id": uuid.uuid4(), "surv": surv_msg_id, "fid": folder_id, "uid": uid},
        )
    conn.execute(sa.text("DELETE FROM message_locations WHERE message_id = :dup"), {"dup": dup_msg_id})

    has_surv_body = conn.execute(
        sa.text("SELECT 1 FROM message_bodies WHERE message_id = :surv LIMIT 1"), {"surv": surv_msg_id}
    ).first()
    if has_surv_body is None:
        conn.execute(sa.text("UPDATE message_bodies SET message_id = :surv WHERE message_id = :dup"), params)
    else:
        conn.execute(sa.text("DELETE FROM message_bodies WHERE message_id = :dup"), {"dup": dup_msg_id})

    surv_arch = conn.execute(
        sa.text("SELECT state FROM message_archive_state WHERE message_id = :surv"), {"surv": surv_msg_id}
    ).scalar_one_or_none()
    dup_arch = conn.execute(
        sa.text("SELECT state FROM message_archive_state WHERE message_id = :dup"), {"dup": dup_msg_id}
    ).scalar_one_or_none()
    if dup_arch is not None:
        if surv_arch is None:
            conn.execute(sa.text("UPDATE message_archive_state SET message_id = :surv WHERE message_id = :dup"), params)
        elif surv_arch != "archive_complete" and dup_arch == "archive_complete":
            conn.execute(sa.text("DELETE FROM message_archive_state WHERE message_id = :surv"), {"surv": surv_msg_id})
            conn.execute(sa.text("UPDATE message_archive_state SET message_id = :surv WHERE message_id = :dup"), params)
        else:
            conn.execute(sa.text("DELETE FROM message_archive_state WHERE message_id = :dup"), {"dup": dup_msg_id})

    dropped_blobs: dict[uuid.UUID, int] = {}
    surv_blob = conn.execute(
        sa.text("SELECT blob_id FROM message_blob_links WHERE message_id = :surv"), {"surv": surv_msg_id}
    ).scalar_one_or_none()
    dup_blob = conn.execute(
        sa.text("SELECT blob_id FROM message_blob_links WHERE message_id = :dup"), {"dup": dup_msg_id}
    ).scalar_one_or_none()
    if dup_blob is not None:
        if surv_blob is None:
            conn.execute(sa.text("UPDATE message_blob_links SET message_id = :surv WHERE message_id = :dup"), params)
        else:
            conn.execute(sa.text("DELETE FROM message_blob_links WHERE message_id = :dup"), {"dup": dup_msg_id})
            dropped_blobs[dup_blob] = dropped_blobs.get(dup_blob, 0) + 1

    has_surv_att = conn.execute(
        sa.text("SELECT 1 FROM attachments WHERE message_id = :surv LIMIT 1"), {"surv": surv_msg_id}
    ).first()
    if has_surv_att is None:
        conn.execute(sa.text("UPDATE attachments SET message_id = :surv WHERE message_id = :dup"), params)
    else:
        att_blobs = conn.execute(
            sa.text("SELECT blob_id, COUNT(*) FROM attachments WHERE message_id = :dup AND blob_id IS NOT NULL GROUP BY blob_id"),
            {"dup": dup_msg_id},
        ).all()
        for bid, cnt in att_blobs:
            dropped_blobs[bid] = dropped_blobs.get(bid, 0) + int(cnt)
        conn.execute(sa.text("DELETE FROM attachments WHERE message_id = :dup"), {"dup": dup_msg_id})

    for bid, dec in dropped_blobs.items():
        if dec > 0:
            conn.execute(
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
                {"bid": bid, "dec": dec},
            )

    conn.execute(
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
    conn.execute(sa.text("DELETE FROM thread_messages WHERE message_id = :dup"), {"dup": dup_msg_id})

    has_surv_search = conn.execute(
        sa.text("SELECT 1 FROM message_search WHERE message_id = :surv LIMIT 1"), {"surv": surv_msg_id}
    ).first()
    if has_surv_search is None:
        conn.execute(sa.text("UPDATE message_search SET message_id = :surv WHERE message_id = :dup"), params)
    else:
        conn.execute(sa.text("DELETE FROM message_search WHERE message_id = :dup"), {"dup": dup_msg_id})

    conn.execute(sa.text("UPDATE blob_quota_reservations SET message_id = :surv WHERE message_id = :dup"), params)
    conn.execute(
        sa.text(
            """
            INSERT INTO message_remote_image_allows (message_id, created_at)
            SELECT :surv, created_at FROM message_remote_image_allows WHERE message_id = :dup
            ON CONFLICT (message_id) DO NOTHING
            """
        ),
        params,
    )
    conn.execute(sa.text("DELETE FROM message_remote_image_allows WHERE message_id = :dup"), {"dup": dup_msg_id})
    conn.execute(sa.text("DELETE FROM messages WHERE id = :dup"), {"dup": dup_msg_id})


def _rewrite_single_remote_op_sql(
    conn: sa.Connection,
    *,
    op_id: uuid.UUID,
    entity_key: str,
    desired_state: dict | None,
    remapped_msg_rids: dict[str, str],
    safe_old: str,
    old_remote_id: str,
    new_remote_id: str,
) -> None:
    desired = dict(desired_state or {})
    changed = False
    msg_rid = desired.get("remote_id")
    if isinstance(msg_rid, str):
        new_msg_rid = remapped_msg_rids.get(msg_rid)
        if new_msg_rid is None:
            parsed = _parse_imap_remote_id(msg_rid)
            if parsed is not None and parsed[1] == safe_old:
                new_msg_rid = _format_imap_remote_id(new_remote_id, parsed[0], parsed[2])
        if new_msg_rid is not None and new_msg_rid != msg_rid:
            desired["remote_id"] = new_msg_rid
            changed = True
            old_prefix = f"msg:{msg_rid}:"
            if entity_key.startswith(old_prefix):
                entity_key = f"msg:{new_msg_rid}:{entity_key[len(old_prefix):]}"
    for key in _REMOTE_OP_FOLDER_KEYS:
        if desired.get(key) == old_remote_id:
            desired[key] = new_remote_id
            changed = True
    if changed:
        conn.execute(
            sa.text("UPDATE remote_operations SET entity_key = :ek, desired_state = CAST(:ds AS jsonb) WHERE id = :id"),
            {"ek": entity_key, "ds": json.dumps(desired), "id": op_id},
        )


def _rewrite_coalesced_container_message_paths(
    conn: sa.Connection,
    *,
    account_id: uuid.UUID,
    old_remote_id: str,
    new_remote_id: str,
) -> None:
    if not old_remote_id or old_remote_id == new_remote_id:
        return
    safe_old = old_remote_id.replace(_IMAP_REMOTE_SEP, " ")
    pattern = f"%{_IMAP_REMOTE_SEP}{_escape_like(safe_old)}{_IMAP_REMOTE_SEP}%"
    msg_rows = conn.execute(
        sa.text("SELECT id, remote_id FROM messages WHERE account_id = :aid AND remote_id LIKE :pat ESCAPE '\\'"),
        {"aid": account_id, "pat": pattern},
    ).all()

    remapped_msg_rids: dict[str, str] = {}
    for msg_id, old_msg_rid in msg_rows:
        parsed = _parse_imap_remote_id(old_msg_rid)
        if parsed is None or parsed[1] != safe_old:
            continue
        new_msg_rid = _format_imap_remote_id(new_remote_id, parsed[0], parsed[2])
        remapped_msg_rids[old_msg_rid] = new_msg_rid
        surv_msg_id = conn.execute(
            sa.text("SELECT id FROM messages WHERE account_id = :aid AND remote_id = :rid"),
            {"aid": account_id, "rid": new_msg_rid},
        ).scalar_one_or_none()
        if surv_msg_id is not None and surv_msg_id != msg_id:
            _merge_duplicate_message_sql(conn, dup_msg_id=msg_id, surv_msg_id=surv_msg_id)
        else:
            conn.execute(
                sa.text("UPDATE messages SET remote_id = :new_rid WHERE id = :mid"),
                {"new_rid": new_msg_rid, "mid": msg_id},
            )

    op_rows = conn.execute(
        sa.text("SELECT id, entity_key, desired_state FROM remote_operations WHERE account_id = :aid AND status != 'done'"),
        {"aid": account_id},
    ).mappings().all()
    for op in op_rows:
        _rewrite_single_remote_op_sql(
            conn,
            op_id=op["id"],
            entity_key=str(op["entity_key"]),
            desired_state=op["desired_state"],
            remapped_msg_rids=remapped_msg_rids,
            safe_old=safe_old,
            old_remote_id=old_remote_id,
            new_remote_id=new_remote_id,
        )


def _coalesce_pick_key(row: dict, *, epoch_min: datetime) -> tuple[int, float, float, int, str]:
    updated = row["updated_at"] or epoch_min
    created = row["created_at"] or epoch_min
    return (
        0 if row["remote_state"] == "active" else 1,
        -updated.timestamp(),
        -created.timestamp(),
        0 if str(row["remote_id"]).isascii() else 1,
        str(row["id"]),
    )


def _migrate_coalesced_checkpoint(
    conn: sa.Connection,
    *,
    account_id: uuid.UUID,
    survivor_id: uuid.UUID,
    donor_id: uuid.UUID,
) -> None:
    surv_cp = conn.execute(
        sa.text(
            "SELECT full_scan_complete, uidvalidity FROM sync_checkpoints "
            "WHERE account_id = :aid AND folder_id = :fid"
        ),
        {"aid": account_id, "fid": survivor_id},
    ).mappings().first()
    donor_cp = conn.execute(
        sa.text(
            "SELECT full_scan_complete, uidvalidity FROM sync_checkpoints "
            "WHERE account_id = :aid AND folder_id = :fid"
        ),
        {"aid": account_id, "fid": donor_id},
    ).mappings().first()
    if surv_cp is None and donor_cp is not None:
        conn.execute(
            sa.text("UPDATE sync_checkpoints SET folder_id = :surv WHERE account_id = :aid AND folder_id = :donor"),
            {"aid": account_id, "surv": survivor_id, "donor": donor_id},
        )
        return
    can_promote_donor = (
        surv_cp is not None
        and donor_cp is not None
        and not surv_cp["full_scan_complete"]
        and donor_cp["full_scan_complete"]
        and (
            surv_cp["uidvalidity"] is None
            or donor_cp["uidvalidity"] is None
            or surv_cp["uidvalidity"] == donor_cp["uidvalidity"]
        )
    )
    if can_promote_donor:
        conn.execute(
            sa.text("DELETE FROM sync_checkpoints WHERE account_id = :aid AND folder_id = :surv"),
            {"aid": account_id, "surv": survivor_id},
        )
        conn.execute(
            sa.text("UPDATE sync_checkpoints SET folder_id = :surv WHERE account_id = :aid AND folder_id = :donor"),
            {"aid": account_id, "surv": survivor_id, "donor": donor_id},
        )
        return
    conn.execute(
        sa.text("DELETE FROM sync_checkpoints WHERE account_id = :aid AND folder_id = :donor"),
        {"aid": account_id, "donor": donor_id},
    )


def _migrate_coalesced_donor(
    conn: sa.Connection,
    *,
    account_id: uuid.UUID,
    kind: str,
    survivor: dict,
    donor: dict,
) -> None:
    survivor_id = survivor["id"]
    donor_id = donor["id"]
    donor_locs = conn.execute(
        sa.text("SELECT message_id, uid FROM message_locations WHERE folder_id = :fid"),
        {"fid": donor_id},
    ).all()
    for msg_id, uid in donor_locs:
        conn.execute(
            sa.text(
                """
                INSERT INTO message_locations (id, message_id, folder_id, uid)
                VALUES (:id, :mid, :fid, :uid)
                ON CONFLICT (message_id, folder_id) DO NOTHING
                """
            ),
            {"id": uuid.uuid4(), "mid": msg_id, "fid": survivor_id, "uid": uid},
        )
    conn.execute(sa.text("DELETE FROM message_locations WHERE folder_id = :fid"), {"fid": donor_id})

    if kind == "container":
        _rewrite_coalesced_container_message_paths(
            conn,
            account_id=account_id,
            old_remote_id=str(donor["remote_id"]),
            new_remote_id=str(survivor["remote_id"]),
        )

    _migrate_coalesced_checkpoint(conn, account_id=account_id, survivor_id=survivor_id, donor_id=donor_id)

    has_survivor_patrol = conn.execute(
        sa.text("SELECT 1 FROM folder_patrol_status WHERE folder_id = :fid LIMIT 1"),
        {"fid": survivor_id},
    ).first()
    if has_survivor_patrol is None:
        conn.execute(
            sa.text("UPDATE folder_patrol_status SET folder_id = :surv WHERE folder_id = :donor"),
            {"surv": survivor_id, "donor": donor_id},
        )
    else:
        conn.execute(sa.text("DELETE FROM folder_patrol_status WHERE folder_id = :donor"), {"donor": donor_id})

    conn.execute(
        sa.text("UPDATE sync_request_targets SET folder_id = :surv WHERE folder_id = :donor"),
        {"surv": survivor_id, "donor": donor_id},
    )
    conn.execute(
        sa.text("UPDATE sync_request_target_jobs SET folder_id = :surv WHERE folder_id = :donor"),
        {"surv": survivor_id, "donor": donor_id},
    )
    conn.execute(sa.text("DELETE FROM folder_stats WHERE folder_id = :donor"), {"donor": donor_id})
    conn.execute(sa.text("DELETE FROM folders WHERE id = :donor"), {"donor": donor_id})


def _refresh_coalesced_container_stats(conn: sa.Connection, *, survivor_id: uuid.UUID) -> None:
    stats_row = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE m.is_read IS FALSE) AS unread,
                   COUNT(*) FILTER (WHERE m.is_read IS NULL) AS unknown_read
              FROM message_locations ml
              JOIN messages m ON m.id = ml.message_id
             WHERE ml.folder_id = :fid
            """
        ),
        {"fid": survivor_id},
    ).mappings().one()
    total = int(stats_row["total"] or 0)
    unread_count = None if int(stats_row["unknown_read"] or 0) > 0 else int(stats_row["unread"] or 0)
    conn.execute(
        sa.text(
            """
            INSERT INTO folder_stats (folder_id, total_count, unread_count, updated_at)
            VALUES (:fid, :total, :unread, now())
            ON CONFLICT (folder_id) DO UPDATE
               SET total_count = EXCLUDED.total_count,
                   unread_count = EXCLUDED.unread_count,
                   updated_at = now()
            """
        ),
        {"fid": survivor_id, "total": total, "unread": unread_count},
    )


def _coalesce_gmail_duplicate_folders(conn: sa.Connection) -> None:
    """Merge multi-language duplicate Gmail system folders created before rebinding."""
    rows = conn.execute(
        sa.text(
            f"""
            SELECT f.id, f.account_id, f.remote_id, f.role, f.kind, f.selectable,
                   f.remote_state, f.created_at, f.updated_at
              FROM folders f
              JOIN accounts a ON a.id = f.account_id
             WHERE ({_GMAIL_ACCOUNT_PREDICATE})
               AND f.role IN :roles
               AND f.remote_id LIKE '[Gmail]/%'
            """
        ).bindparams(sa.bindparam("roles", value=list(_GMAIL_SYSTEM_ROLES), expanding=True))
    ).mappings().all()

    groups: dict[tuple[uuid.UUID, str, str], list[dict]] = {}
    for row in rows:
        key = (row["account_id"], row["kind"], row["role"])
        groups.setdefault(key, []).append(dict(row))

    epoch_min = datetime.min.replace(tzinfo=timezone.utc)
    for (aid, kind, _role), group in groups.items():
        if len(group) <= 1:
            continue
        ordered = sorted(group, key=lambda item: _coalesce_pick_key(item, epoch_min=epoch_min))
        survivor = ordered[0]
        for donor in ordered[1:]:
            _migrate_coalesced_donor(conn, account_id=aid, kind=kind, survivor=survivor, donor=donor)
        if kind == "container":
            _refresh_coalesced_container_stats(conn, survivor_id=survivor["id"])


def upgrade() -> None:
    op.add_column(
        "folders",
        sa.Column("selectable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "folders",
        sa.Column("remote_state", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
    )

    op.execute(
        sa.text(
            """
            UPDATE folders f
               SET selectable = CASE
                       WHEN f.remote_id = '[Gmail]' AND EXISTS (
                           SELECT 1 FROM accounts a WHERE a.id = f.account_id AND ({_GMAIL_ACCOUNT_PREDICATE})
                       ) THEN false
                       WHEN f.kind = 'container' AND f.sync_status = 'paused' AND EXISTS (
                           SELECT 1 FROM folders c
                            WHERE c.account_id = f.account_id AND c.parent_remote_id = f.remote_id
                       ) THEN false
                       ELSE true
                   END,
                   remote_state = CASE
                       WHEN f.remote_id = '[Gmail]' AND EXISTS (
                           SELECT 1 FROM accounts a WHERE a.id = f.account_id AND ({_GMAIL_ACCOUNT_PREDICATE})
                       ) THEN 'active'
                       WHEN f.kind = 'container' AND f.sync_status = 'paused' AND NOT EXISTS (
                           SELECT 1 FROM folders c
                            WHERE c.account_id = f.account_id AND c.parent_remote_id = f.remote_id
                       ) THEN 'missing'
                       ELSE 'active'
                   END
            """.replace("{_GMAIL_ACCOUNT_PREDICATE}", _GMAIL_ACCOUNT_PREDICATE)
        )
    )

    # Repair legacy Important / All Mail views that fell into role='other'.
    op.execute(
        sa.text(
            f"""
            UPDATE folders f
               SET role = 'important', kind = 'view', selectable = true
             WHERE f.remote_id IN :imp_ids
               AND EXISTS (SELECT 1 FROM accounts a WHERE a.id = f.account_id AND ({_GMAIL_ACCOUNT_PREDICATE}))
            """
        ).bindparams(sa.bindparam("imp_ids", value=list(_GMAIL_IMPORTANT_IDS), expanding=True))
    )
    op.execute(
        sa.text(
            f"""
            UPDATE folders f
               SET role = 'all', kind = 'view', selectable = true
             WHERE f.remote_id IN :all_ids
               AND EXISTS (SELECT 1 FROM accounts a WHERE a.id = f.account_id AND ({_GMAIL_ACCOUNT_PREDICATE}))
            """
        ).bindparams(sa.bindparam("all_ids", value=list(_GMAIL_ALL_IDS), expanding=True))
    )

    _coalesce_gmail_duplicate_folders(op.get_bind())

    op.create_check_constraint(
        "ck_folders_remote_state",
        "folders",
        "remote_state IN ('active', 'missing')",
    )
    op.drop_column("folders", "sync_status")


def downgrade() -> None:
    op.drop_constraint("ck_folders_remote_state", "folders", type_="check")
    op.add_column(
        "folders",
        sa.Column("sync_status", sa.String(length=32), nullable=False, server_default=sa.text("'idle'")),
    )
    op.execute(
        sa.text(
            """
            UPDATE folders
               SET sync_status = CASE
                   WHEN kind = 'container' AND (NOT selectable OR remote_state = 'missing') THEN 'paused'
                   ELSE 'idle'
               END
            """
        )
    )
    op.drop_column("folders", "remote_state")
    op.drop_column("folders", "selectable")
