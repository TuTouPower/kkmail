"""Tests for t092 AC-001/AC-002/AC-003: orthogonal Folder state, IMAP roles, and system folder rebinding."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from mail_core.db.baseline import CURRENT_HEAD_REVISION
from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import create_sync_request
from mail_core.mail.domain.enums import ExecutionOrigin, FolderRole, JobType
from mail_core.mail.domain.folder_views import CONTAINER, VIEW
from mail_core.mail.storage.models import (
    Account,
    Folder,
    FolderPatrolStatus,
    Message,
    MessageLocation,
    RemoteOperation,
    SyncCheckpoint,
    SyncRequest,
    SyncRequestTarget,
    WorkerJob,
)
from mail_core.providers.base import RemoteFolder
from mail_core.providers.imap import ImapProvider, format_imap_remote_id, parse_imap_remote_id
from mail_core.sync import engine, reconcile as reconcile_mod

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = str(ROOT / "src/mail_core/db/alembic.ini")

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _alembic_config_for(url: str) -> Config:
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("script_location", str(ROOT / "src/mail_core/db/alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


class _FakeGmailImap:
    def __init__(self, lines: list[bytes] | None = None) -> None:
        self._lines = lines or [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
            b'(\\HasNoChildren \\Important) "/" "[Gmail]/Important"',
            b'(\\HasNoChildren) "/" "[Gmail]/&kc2JgQ-"',
            b'(\\HasNoChildren \\Important) "/" "My Custom Priority"',
            b'(\\HasNoChildren \\Flagged) "/" "[Gmail]/Starred"',
            b'(\\HasNoChildren) "/" "[Gmail]/&XfJSoGYfaAc-"',
            b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
            b'(\\HasNoChildren) "/" "[Gmail]/&YkBnCZCuTvY-"',
            b'(\\HasNoChildren) "/" "[Gmail]/Sent Mail"',
            b'(\\HasNoChildren) "/" "[Gmail]/&XfJT0ZCuTvY-"',
            b'(\\HasNoChildren) "/" "[Gmail]/Drafts"',
            b'(\\HasNoChildren) "/" "[Gmail]/&g0l6Pw-"',
            b'(\\HasNoChildren) "/" "[Gmail]/Spam"',
            b'(\\HasNoChildren) "/" "[Gmail]/&V4NXPpCuTvY-"',
            b'(\\HasNoChildren) "/" "[Gmail]/Bin"',
            b'(\\HasNoChildren) "/" "[Gmail]/Important Clients"',
            b'(\\HasNoChildren) "/" "[Gmail]/&kc2JgQhbW2I-"',
            b'(\\HasNoChildren) "/" "Sent Backup"',
        ]

    def list(self):
        return "OK", self._lines

    def logout(self):
        return "OK", []


def test_ac002_folder_role_enum_and_imap_important_and_prefix_mapping(monkeypatch):
    """AC-002: FolderRole includes flagged/important and IMAP resolves \\Important & [Gmail]/ names."""
    assert FolderRole.FLAGGED.value == "flagged"
    assert FolderRole.IMPORTANT.value == "important"

    provider = ImapProvider("imap.gmail.com", 993, "user@gmail.com", "pw", use_ssl=False)
    monkeypatch.setattr(provider, "_connect_with_permit", lambda: (_FakeGmailImap(), None))
    catalog = {rf.remote_id: rf for rf in provider.list_folder_catalog()}

    assert catalog["INBOX"].role == FolderRole.INBOX.value
    assert catalog["[Gmail]"].selectable is False
    assert catalog["[Gmail]/Important"].role == FolderRole.IMPORTANT.value
    assert catalog["[Gmail]/&kc2JgQ-"].role == FolderRole.IMPORTANT.value
    assert catalog["My Custom Priority"].role == FolderRole.IMPORTANT.value
    assert catalog["[Gmail]/Starred"].role == FolderRole.FLAGGED.value
    assert catalog["[Gmail]/&XfJSoGYfaAc-"].role == FolderRole.FLAGGED.value
    assert catalog["[Gmail]/All Mail"].role == FolderRole.ALL.value
    assert catalog["[Gmail]/&YkBnCZCuTvY-"].role == FolderRole.ALL.value
    assert catalog["[Gmail]/Sent Mail"].role == FolderRole.SENT.value
    assert catalog["[Gmail]/&XfJT0ZCuTvY-"].role == FolderRole.SENT.value
    assert catalog["[Gmail]/Drafts"].role == FolderRole.DRAFTS.value
    assert catalog["[Gmail]/&g0l6Pw-"].role == FolderRole.DRAFTS.value
    assert catalog["[Gmail]/Spam"].role == FolderRole.JUNK.value
    assert catalog["[Gmail]/&V4NXPpCuTvY-"].role == FolderRole.JUNK.value
    assert catalog["[Gmail]/Bin"].role == FolderRole.TRASH.value
    assert catalog["[Gmail]/Important Clients"].role == FolderRole.OTHER.value
    assert catalog["[Gmail]/&kc2JgQhbW2I-"].role == FolderRole.OTHER.value
    assert catalog["Sent Backup"].role == FolderRole.OTHER.value


@pytestmark_db
def test_ac002_imap_catalog_persists_roles_and_orthogonal_fields(monkeypatch):
    """AC-002: ImapProvider catalog sync persists roles, kind, and selectable into Postgres."""
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"imap-sync-{uuid.uuid4().hex[:8]}@gmail.com",
            provider="imap",
            config={"imap_host": "imap.gmail.com"},
            sync_enabled=True,
        )
        session.add(acc)
        session.commit()
        account_id = acc.id

    imap_lines = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
        b'(\\HasNoChildren \\Important) "/" "My Custom Priority"',
        b'(\\HasNoChildren) "/" "[Gmail]/&XfJSoGYfaAc-"',
        b'(\\HasNoChildren) "/" "[Gmail]/&g0l6Pw-"',
        b'(\\HasNoChildren) "/" "[Gmail]/&V4NXPpCuTvY-"',
        b'(\\HasNoChildren) "/" "[Gmail]/&kc2JgQhbW2I-"',
        b'(\\HasNoChildren) "/" "Sent Backup"',
    ]
    provider = ImapProvider("imap.gmail.com", 993, "imap-sync@gmail.com", "pw", use_ssl=False)
    monkeypatch.setattr(provider, "_connect_with_permit", lambda: (_FakeGmailImap(imap_lines), None))
    monkeypatch.setattr(engine, "build_provider", lambda *_a, **_k: provider)

    assert engine.sync_account_folders(account_id, worker_id="w-imap", store=object(), execution_origin=ExecutionOrigin.FOREGROUND)["status"] == "ok"

    with Session() as session:
        by_rid = {
            f.remote_id: f
            for f in session.scalars(select(Folder).where(Folder.account_id == account_id)).all()
        }
        assert by_rid["My Custom Priority"].role == FolderRole.IMPORTANT.value
        assert by_rid["My Custom Priority"].kind == VIEW
        assert by_rid["[Gmail]/&XfJSoGYfaAc-"].role == FolderRole.FLAGGED.value
        assert by_rid["[Gmail]/&XfJSoGYfaAc-"].kind == CONTAINER
        assert by_rid["[Gmail]/&g0l6Pw-"].role == FolderRole.DRAFTS.value
        assert by_rid["[Gmail]/&g0l6Pw-"].kind == CONTAINER
        assert by_rid["[Gmail]/&V4NXPpCuTvY-"].role == FolderRole.JUNK.value
        assert by_rid["[Gmail]/&V4NXPpCuTvY-"].kind == CONTAINER
        assert by_rid["[Gmail]/&kc2JgQhbW2I-"].role == FolderRole.OTHER.value
        assert by_rid["Sent Backup"].role == FolderRole.OTHER.value
        assert by_rid["[Gmail]"].selectable is False


@pytestmark_db
def test_ac001_migration_0007_replaces_sync_status_and_coalesces_duplicates():
    """AC-001: 0006->0007 replaces sync_status with selectable/remote_state and cleans historical duplicates."""
    parsed = make_url(os.environ["MAIL_CORE_DATABASE_URL"])
    db_name = f"kkmail_mig0007_{uuid.uuid4().hex[:16]}"
    admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)
    temp_url = parsed.set(database=db_name).render_as_string(hide_password=False)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    target = create_engine(temp_url, poolclass=NullPool)
    cfg = _alembic_config_for(temp_url)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))

        command.upgrade(cfg, "20261125_0006")

        gmail_id = uuid.uuid4()
        qq_id = uuid.uuid4()
        m1, m2, m2_en, m3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        blob_dup, blob_surv = uuid.uuid4(), uuid.uuid4()
        op_sent_id = uuid.uuid4()
        ids = {
            k: uuid.uuid4()
            for k in (
                "g_root", "g_all_zh", "g_all_en", "g_imp_zh", "g_imp_en",
                "g_sent_zh", "g_sent_en", "g_draft_zh", "g_draft_en",
                "qq_other", "qq_child", "qq_deleted", "qq_arch_a", "qq_arch_b",
            )
        }
        now = datetime.now(timezone.utc)
        with target.begin() as conn:
            conn.execute(
                text("INSERT INTO accounts (id, email, provider, config) VALUES (:id, :email, 'imap', CAST(:cfg AS jsonb))"),
                [
                    {"id": gmail_id, "email": "dup@gmail.com", "cfg": '{"imap_host": "imap.gmail.com"}'},
                    {"id": qq_id, "email": "qq@qq.com", "cfg": '{"imap_host": "imap.qq.com"}'},
                ],
            )
            conn.execute(
                text("INSERT INTO messages (id, account_id, remote_id, subject, is_read) VALUES (:id, :aid, :rid, :subj, :read)"),
                [
                    {"id": m1, "aid": gmail_id, "rid": "5\x1f[Gmail]/&XfJT0ZCuTvY-\x1f1", "subj": "M1", "read": False},
                    {"id": m2, "aid": gmail_id, "rid": "5\x1f[Gmail]/&XfJT0ZCuTvY-\x1f2", "subj": "M2-zh", "read": True},
                    {"id": m2_en, "aid": gmail_id, "rid": "5\x1f[Gmail]/Sent Mail\x1f2", "subj": "M2-en", "read": True},
                    {"id": m3, "aid": gmail_id, "rid": "6\x1fINBOX\x1f3", "subj": "M3-unknown", "read": None},
                ],
            )
            conn.execute(
                text(
                    "INSERT INTO message_blobs (id, content_sha256, key_version, size_bytes, storage_path, ref_count) "
                    "VALUES (:id, :sha, 1, 12, :path, 1)"
                ),
                [
                    {"id": blob_dup, "sha": "a" * 64, "path": "blobs/dup.bin"},
                    {"id": blob_surv, "sha": "b" * 64, "path": "blobs/surv.bin"},
                ],
            )
            conn.execute(
                text("INSERT INTO message_blob_links (message_id, blob_id) VALUES (:mid, :bid)"),
                [{"mid": m2, "bid": blob_dup}, {"mid": m2_en, "bid": blob_surv}],
            )
            conn.execute(text("INSERT INTO message_bodies (message_id, text_plain) VALUES (:mid, :body)"), [{"mid": m2, "body": "preserved body"}])
            conn.execute(
                text(
                    "INSERT INTO remote_operations (id, account_id, entity_key, op_type, desired_state, status) "
                    "VALUES (:id, :aid, :ek, 'mark_read', CAST(:ds AS jsonb), 'pending')"
                ),
                {
                    "id": op_sent_id,
                    "aid": gmail_id,
                    "ek": "msg:5\x1f[Gmail]/&XfJT0ZCuTvY-\x1f1:read",
                    "ds": '{"remote_id": "5\\u001f[Gmail]/&XfJT0ZCuTvY-\\u001f1", "folder_remote_id": "[Gmail]/&XfJT0ZCuTvY-", "is_read": true}',
                },
            )
            conn.execute(
                text(
                    "INSERT INTO folders (id, account_id, remote_id, name, role, kind, parent_remote_id, sync_status, created_at, updated_at) "
                    "VALUES (:id, :aid, :rid, :name, :role, :kind, :parent, :status, :ts, :ts)"
                ),
                [
                    {"id": ids["g_root"], "aid": gmail_id, "rid": "[Gmail]", "name": "[Gmail]", "role": "other", "kind": "container", "parent": None, "status": "paused", "ts": "2026-10-26T00:00:00Z"},
                    {"id": ids["g_all_zh"], "aid": gmail_id, "rid": "[Gmail]/&YkBnCZCuTvY-", "name": "[Gmail]/所有邮件", "role": "all", "kind": "view", "parent": "[Gmail]", "status": "idle", "ts": "2026-10-26T00:00:00Z"},
                    {"id": ids["g_all_en"], "aid": gmail_id, "rid": "[Gmail]/All Mail", "name": "[Gmail]/All Mail", "role": "all", "kind": "view", "parent": "[Gmail]", "status": "idle", "ts": "2026-11-25T00:00:00Z"},
                    {"id": ids["g_imp_zh"], "aid": gmail_id, "rid": "[Gmail]/&kc2JgQ-", "name": "[Gmail]/重要", "role": "other", "kind": "view", "parent": "[Gmail]", "status": "idle", "ts": "2026-10-26T00:00:00Z"},
                    {"id": ids["g_imp_en"], "aid": gmail_id, "rid": "[Gmail]/Important", "name": "[Gmail]/Important", "role": "other", "kind": "view", "parent": "[Gmail]", "status": "idle", "ts": "2026-11-25T00:00:00Z"},
                    {"id": ids["g_sent_zh"], "aid": gmail_id, "rid": "[Gmail]/&XfJT0ZCuTvY-", "name": "[Gmail]/已发邮件", "role": "sent", "kind": "container", "parent": "[Gmail]", "status": "paused", "ts": "2026-10-26T00:00:00Z"},
                    {"id": ids["g_sent_en"], "aid": gmail_id, "rid": "[Gmail]/Sent Mail", "name": "[Gmail]/Sent Mail", "role": "sent", "kind": "container", "parent": "[Gmail]", "status": "idle", "ts": "2026-11-25T00:00:00Z"},
                    {"id": ids["g_draft_zh"], "aid": gmail_id, "rid": "[Gmail]/&g0l6Pw-", "name": "[Gmail]/草稿", "role": "drafts", "kind": "container", "parent": "[Gmail]", "status": "paused", "ts": "2026-10-26T00:00:00Z"},
                    {"id": ids["g_draft_en"], "aid": gmail_id, "rid": "[Gmail]/Drafts", "name": "[Gmail]/Drafts", "role": "drafts", "kind": "container", "parent": "[Gmail]", "status": "idle", "ts": "2026-11-25T00:00:00Z"},
                    {"id": ids["qq_other"], "aid": qq_id, "rid": "Other", "name": "其他文件夹", "role": "other", "kind": "container", "parent": None, "status": "paused", "ts": "2026-10-26T00:00:00Z"},
                    {"id": ids["qq_child"], "aid": qq_id, "rid": "Other/Sub", "name": "Sub", "role": "other", "kind": "container", "parent": "Other", "status": "idle", "ts": "2026-10-26T00:00:00Z"},
                    {"id": ids["qq_deleted"], "aid": qq_id, "rid": "GoneFolder", "name": "GoneFolder", "role": "other", "kind": "container", "parent": None, "status": "paused", "ts": "2026-10-26T00:00:00Z"},
                    {"id": ids["qq_arch_a"], "aid": qq_id, "rid": "NonGmailA", "name": "NonGmailA", "role": "archive", "kind": "container", "parent": None, "status": "idle", "ts": "2026-10-26T00:00:00Z"},
                    {"id": ids["qq_arch_b"], "aid": qq_id, "rid": "NonGmailB", "name": "NonGmailB", "role": "archive", "kind": "container", "parent": None, "status": "idle", "ts": "2026-11-25T00:00:00Z"},
                ],
            )
            conn.execute(
                text("INSERT INTO message_locations (id, message_id, folder_id, uid) VALUES (:id, :mid, :fid, :uid)"),
                [
                    {"id": uuid.uuid4(), "mid": m1, "fid": ids["g_imp_zh"], "uid": None},
                    {"id": uuid.uuid4(), "mid": m2_en, "fid": ids["g_imp_zh"], "uid": None},
                    {"id": uuid.uuid4(), "mid": m2_en, "fid": ids["g_imp_en"], "uid": None},
                    {"id": uuid.uuid4(), "mid": m3, "fid": ids["g_imp_en"], "uid": None},
                    {"id": uuid.uuid4(), "mid": m1, "fid": ids["g_sent_zh"], "uid": 1},
                    {"id": uuid.uuid4(), "mid": m2, "fid": ids["g_sent_zh"], "uid": 2},
                    {"id": uuid.uuid4(), "mid": m2_en, "fid": ids["g_sent_en"], "uid": 2},
                    {"id": uuid.uuid4(), "mid": m3, "fid": ids["g_draft_zh"], "uid": 10},
                ],
            )
            conn.execute(
                text(
                    "INSERT INTO sync_checkpoints (account_id, folder_id, cursor, uidvalidity, full_scan_complete) "
                    "VALUES (:aid, :fid, CAST(:cur AS jsonb), 5, :done)"
                ),
                [
                    {"aid": gmail_id, "fid": ids["g_sent_zh"], "cur": '{"uid_next": 50}', "done": True},
                    {"aid": gmail_id, "fid": ids["g_sent_en"], "cur": '{"uid_next": 1}', "done": False},
                ],
            )
            conn.execute(
                text(
                    "INSERT INTO folder_patrol_status (folder_id, last_status, last_probe_failures, created_at, updated_at) "
                    "VALUES (:fid, CAST(:st AS jsonb), 0, :ts, :ts)"
                ),
                {"fid": ids["g_sent_zh"], "st": '{"state": "ok"}', "ts": now},
            )

        assert CURRENT_HEAD_REVISION == "20261126_0007"
        assert ScriptDirectory.from_config(cfg).get_heads() == ["20261126_0007"]

        command.upgrade(cfg, "head")

        with target.connect() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("folders")}
            assert "sync_status" not in cols
            assert {"kind", "selectable", "remote_state"} <= cols

            by_rid = {
                row[0]: row
                for row in conn.execute(
                    text("SELECT remote_id, role, kind, selectable, remote_state FROM folders WHERE account_id = :aid"),
                    {"aid": gmail_id},
                ).all()
            }
            assert set(by_rid) == {"[Gmail]", "[Gmail]/All Mail", "[Gmail]/Drafts", "[Gmail]/Important", "[Gmail]/Sent Mail"}
            assert by_rid["[Gmail]"][3:] == (False, "active")
            assert by_rid["[Gmail]/Important"][1:] == ("important", "view", True, "active")
            assert by_rid["[Gmail]/Sent Mail"][3:] == (True, "active")

            imp_mids = {
                row[0]
                for row in conn.execute(
                    text("SELECT ml.message_id FROM message_locations ml JOIN folders f ON f.id = ml.folder_id WHERE f.account_id = :aid AND f.remote_id = '[Gmail]/Important'"),
                    {"aid": gmail_id},
                ).all()
            }
            assert imp_mids == {m1, m2_en, m3}
            assert conn.execute(text("SELECT remote_id FROM messages WHERE id = :id"), {"id": m1}).scalar_one() == "5\x1f[Gmail]/Sent Mail\x1f1"
            assert conn.execute(text("SELECT id FROM messages WHERE id = :id"), {"id": m2}).scalar_one_or_none() is None
            assert conn.execute(text("SELECT text_plain FROM message_bodies WHERE message_id = :id"), {"id": m2_en}).scalar_one() == "preserved body"
            assert conn.execute(text("SELECT ref_count FROM message_blobs WHERE id = :id"), {"id": blob_dup}).scalar_one() == 0

            op_row = conn.execute(text("SELECT entity_key, desired_state FROM remote_operations WHERE id = :id"), {"id": op_sent_id}).mappings().one()
            assert op_row["entity_key"] == "msg:5\x1f[Gmail]/Sent Mail\x1f1:read"
            assert op_row["desired_state"]["folder_remote_id"] == "[Gmail]/Sent Mail"

            cp_row = conn.execute(text("SELECT full_scan_complete, cursor FROM sync_checkpoints WHERE folder_id = :fid"), {"fid": ids["g_sent_en"]}).mappings().one()
            assert cp_row["full_scan_complete"] is True and cp_row["cursor"] == {"uid_next": 50}
            assert conn.execute(text("SELECT folder_id FROM folder_patrol_status WHERE folder_id = :fid"), {"fid": ids["g_sent_en"]}).scalar_one() == ids["g_sent_en"]
            assert conn.execute(text("SELECT folder_id FROM folder_patrol_status WHERE folder_id = :fid"), {"fid": ids["g_sent_zh"]}).scalar_one_or_none() is None

            sent_stats = conn.execute(text("SELECT total_count, unread_count FROM folder_stats WHERE folder_id = :fid"), {"fid": ids["g_sent_en"]}).mappings().one()
            assert sent_stats["total_count"] == 2 and sent_stats["unread_count"] == 1
            draft_stats = conn.execute(text("SELECT total_count, unread_count FROM folder_stats WHERE folder_id = :fid"), {"fid": ids["g_draft_en"]}).mappings().one()
            assert draft_stats["total_count"] == 1 and draft_stats["unread_count"] is None

            qq_rows = {row[0]: row for row in conn.execute(text("SELECT remote_id, selectable, remote_state FROM folders WHERE account_id = :aid"), {"aid": qq_id}).all()}
            assert qq_rows["Other"][1:] == (False, "active")
            assert qq_rows["Other/Sub"][1:] == (True, "active")
            assert qq_rows["GoneFolder"][2] == "missing"
            assert {"NonGmailA", "NonGmailB"} <= set(qq_rows)

        with target.begin() as conn:
            with pytest.raises(IntegrityError):
                conn.execute(text("INSERT INTO folders (id, account_id, remote_id, name, remote_state) VALUES (:id, :aid, 'Bad', 'Bad', 'paused')"), {"id": uuid.uuid4(), "aid": qq_id})

        command.downgrade(cfg, "20261125_0006")
        with target.connect() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("folders")}
            assert "sync_status" in cols and "remote_state" not in cols and "selectable" not in cols
            down_status = {
                row[0]: row[1]
                for row in conn.execute(
                    text("SELECT remote_id, sync_status FROM folders WHERE account_id IN (:g, :q)"),
                    {"g": gmail_id, "q": qq_id},
                ).all()
            }
            assert down_status["Other"] == "paused"
            assert down_status["GoneFolder"] == "paused"
            assert down_status["Other/Sub"] == "idle"
            assert down_status["[Gmail]/Important"] == "idle"

        command.upgrade(cfg, "head")
    finally:
        target.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin.dispose()


@pytestmark_db
def test_ac003_rebind_patrol_delta_view_disappearance_and_revive(monkeypatch):
    """AC-003: system folders rebind 1-to-1 with delta resume; missing container/view converge & revive."""
    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"rebind-{uuid.uuid4().hex[:8]}@gmail.com", provider="imap", config={"imap_host": "imap.gmail.com"}, sync_enabled=True)
        session.add(account)
        session.commit()
        account_id = account.id

    zh_catalog = [
        RemoteFolder("INBOX", "INBOX", role="inbox", selectable=True),
        RemoteFolder("[Gmail]", "[Gmail]", role="other", selectable=False),
        RemoteFolder("[Gmail]/&XfJT0ZCuTvY-", "[Gmail]/已发邮件", role="sent", parent_remote_id="[Gmail]", selectable=True),
        RemoteFolder("[Gmail]/&YkBnCZCuTvY-", "[Gmail]/所有邮件", role="all", parent_remote_id="[Gmail]", selectable=True),
        RemoteFolder("[Gmail]/&kc2JgQ-", "[Gmail]/重要", role="important", parent_remote_id="[Gmail]", selectable=True),
        RemoteFolder("CustomTemp", "CustomTemp", role="other", selectable=True),
    ]
    en_omit_both_catalog = [
        RemoteFolder("INBOX", "INBOX", role="inbox", selectable=True),
        RemoteFolder("[Gmail]", "[Gmail]", role="other", selectable=False),
        RemoteFolder("[Gmail]/Sent Mail", "[Gmail]/Sent Mail", role="sent", parent_remote_id="[Gmail]", selectable=True),
        RemoteFolder("[Gmail]/Important", "[Gmail]/Important", role="important", parent_remote_id="[Gmail]", selectable=True),
    ]
    revived_catalog = en_omit_both_catalog + [
        RemoteFolder("CustomTemp", "CustomTemp", role="other", selectable=True),
        RemoteFolder("[Gmail]/&YkBnCZCuTvY-", "[Gmail]/所有邮件", role="all", parent_remote_id="[Gmail]", selectable=True),
    ]

    active_catalog = zh_catalog
    monkeypatch.setattr(engine, "build_provider", lambda *_a, **_k: SimpleNamespace(list_folder_catalog=lambda: active_catalog))
    assert engine.sync_account_folders(account_id, worker_id="w1", store=object(), execution_origin=ExecutionOrigin.FOREGROUND)["status"] == "ok"

    now = datetime.now(timezone.utc)
    with Session() as session:
        by_rid = {f.remote_id: f for f in session.scalars(select(Folder).where(Folder.account_id == account_id)).all()}
        sent_id = by_rid["[Gmail]/&XfJT0ZCuTvY-"].id
        all_id = by_rid["[Gmail]/&YkBnCZCuTvY-"].id
        imp_id = by_rid["[Gmail]/&kc2JgQ-"].id
        custom_id = by_rid["CustomTemp"].id
        session.add(SyncCheckpoint(account_id=account_id, folder_id=sent_id, cursor={"uid_next": 10}, uidvalidity=5, full_scan_complete=True))
        session.add(FolderPatrolStatus(folder_id=sent_id, last_status="ok", last_probe_failures=0, created_at=now, updated_at=now))
        sent_msg = Message(account_id=account_id, remote_id=format_imap_remote_id("[Gmail]/&XfJT0ZCuTvY-", 5, 101), subject="Sent one", is_read=False)
        session.add(sent_msg)
        session.flush()
        session.add(MessageLocation(message_id=sent_msg.id, folder_id=sent_id, uid=101))
        stale_sent = Folder(account_id=account_id, remote_id="LegacySentMissing", name="LegacySentMissing", role="sent", kind=CONTAINER, selectable=True, remote_state="missing")
        sent_op = RemoteOperation(
            account_id=account_id,
            entity_key=f"msg:{sent_msg.remote_id}:read",
            op_type="mark_read",
            desired_state={"remote_id": sent_msg.remote_id, "folder_remote_id": "[Gmail]/&XfJT0ZCuTvY-", "is_read": True},
            status="pending",
        )
        session.add_all([stale_sent, sent_op])

        # req_custom via create_sync_request (committed!), verify view folder_id returns empty targets, and seed req_all_view target
        req_custom, _ = create_sync_request(session, client_request_id=f"req-c-{uuid.uuid4().hex}", mode="delta", trigger="manual", scope={"account_id": str(account_id), "folder_id": str(custom_id)}, account_id=account_id, folder_id=custom_id)
        req_all_empty, _ = create_sync_request(session, client_request_id=f"req-ve-{uuid.uuid4().hex}", mode="delta", trigger="manual", scope={"account_id": str(account_id), "folder_id": str(all_id)}, account_id=account_id, folder_id=all_id)
        assert req_all_empty.state == "complete"
        req_all_view = SyncRequest(client_request_id=f"req-v-{uuid.uuid4().hex}", mode="delta", trigger="manual", state="queued", scope={"account_id": str(account_id), "folder_id": str(all_id)}, created_at=now)
        session.add(req_all_view)
        session.flush()
        session.add(SyncRequestTarget(request_id=req_all_view.id, account_id=account_id, folder_id=all_id, target_key=f"account:{account_id}:folder:{all_id}:role:all", requested_generation=uuid.uuid4(), state="queued", created_at=now))
        session.execute(delete(WorkerJob).where(WorkerJob.account_id == account_id))
        session.commit()
        sent_msg_id, sent_op_id, req_custom_id, req_all_view_id = sent_msg.id, sent_op.id, req_custom.id, req_all_view.id

    active_catalog = en_omit_both_catalog
    assert engine.sync_account_folders(account_id, worker_id="w2", store=object(), execution_origin=ExecutionOrigin.FOREGROUND)["status"] == "ok"

    with Session() as session:
        all_rows = session.scalars(select(Folder).where(Folder.account_id == account_id)).all()
        by_id = {f.id: f for f in all_rows}
        assert len([f for f in all_rows if f.role == "sent" and f.remote_state == "active"]) == 1
        assert by_id[sent_id].remote_id == "[Gmail]/Sent Mail" and by_id[sent_id].remote_state == "active"
        assert by_id[imp_id].remote_id == "[Gmail]/Important" and by_id[imp_id].remote_state == "active"
        assert by_id[custom_id].remote_state == "missing" and by_id[all_id].remote_state == "missing"
        assert session.get(FolderPatrolStatus, sent_id) is not None

        step2_jobs = session.scalars(select(WorkerJob).where(WorkerJob.account_id == account_id)).all()
        sent_job_types = [j.job_type for j in step2_jobs if str(sent_id) in (j.dedupe_key or "")]
        assert JobType.SYNC_FOLDER_DELTA.value in sent_job_types
        assert JobType.SYNC_FOLDER_METADATA.value not in sent_job_types

        t_custom = session.scalar(select(SyncRequestTarget).where(SyncRequestTarget.request_id == req_custom_id))
        t_all = session.scalar(select(SyncRequestTarget).where(SyncRequestTarget.request_id == req_all_view_id))
        assert t_custom is not None and t_custom.state == "failed" and t_custom.error_code == "folder_deleted"
        assert t_all is not None and t_all.state == "failed" and t_all.error_code == "folder_deleted"

        expected_sent_rid = format_imap_remote_id("[Gmail]/Sent Mail", 5, 101)
        assert session.get(Message, sent_msg_id).remote_id == expected_sent_rid
        refreshed_op = session.get(RemoteOperation, sent_op_id)
        assert refreshed_op.entity_key == f"msg:{expected_sent_rid}:read"
        assert parse_imap_remote_id(refreshed_op.desired_state["remote_id"])[1] == "[Gmail]/Sent Mail"

    monkeypatch.setattr(reconcile_mod, "build_provider", lambda *_a, **_k: SimpleNamespace(reconcile=lambda _rid, _ids: []))
    assert reconcile_mod.reconcile_folder(account_id, sent_id, worker_id="w-rec")["deleted"] == 0

    with Session() as session:
        session.execute(delete(WorkerJob).where(WorkerJob.account_id == account_id))
        session.commit()

    active_catalog = revived_catalog
    assert engine.sync_account_folders(account_id, worker_id="w3", store=object(), execution_origin=ExecutionOrigin.FOREGROUND)["status"] == "ok"

    with Session() as session:
        assert session.get(Folder, custom_id).remote_state == "active"
        assert session.get(Folder, all_id).remote_state == "active"
        step3_jobs = session.scalars(select(WorkerJob).where(WorkerJob.account_id == account_id)).all()
        custom_jobs = [j for j in step3_jobs if str(custom_id) in (j.dedupe_key or "") or (j.payload or {}).get("folder_id") == str(custom_id)]
        all_jobs = [j for j in step3_jobs if str(all_id) in (j.dedupe_key or "") or (j.payload or {}).get("folder_id") == str(all_id)]
        assert any(j.job_type == JobType.SYNC_FOLDER_METADATA.value for j in custom_jobs)
        assert all_jobs == []
