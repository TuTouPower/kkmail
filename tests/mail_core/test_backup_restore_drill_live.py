"""Live Encrypted Backup & Cross-Database Restore Drill Tests (t019).

Verifies real pg_dump, sealed AES-GCM encryption, checksum verification,
real pg_restore into a fresh database, and complete data/blob decryption assertions.
"""

from __future__ import annotations

import base64
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.backup.crypto import BackupCryptoError, load_backup_keyring
from mail_core.backup.package import create_backup_package, restore_backup_package, verify_backup_package
from mail_core.blobs import BlobStore, load_keyring_from_env
from mail_core.db.session import get_engine, get_session_factory
from mail_core.mail.storage.models import Account, Attachment, Folder, Message, MessageBlob, MessageBlobLink, MessageBody

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _pg_credentials():
    url = URL.create("postgresql+psycopg", username="postgres")
    raw_url = os.environ.get("MAIL_CORE_DATABASE_URL", "")
    from sqlalchemy.engine import make_url

    parsed = make_url(raw_url)
    return parsed.username, parsed.password, parsed.host, parsed.port


# --- AC-001, AC-002, AC-005: Real Encrypted Backup & Full Restore Drill -----------


def test_real_encrypted_backup_and_restore_cycle(tmp_path, monkeypatch):
    """AC-001, AC-002, AC-005: Full round-trip: pg_dump -> AES-GCM -> verify -> pg_restore -> business assertion."""
    # Ensure backup and blob keyrings are active
    backup_key_b64 = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", backup_key_b64)
    keyring = {1: base64.b64decode(backup_key_b64)}

    source_engine = get_engine()
    source_url = os.environ["MAIL_CORE_DATABASE_URL"]

    # 1. Seed rich data in source database
    src_blobs = tmp_path / "src_blobs"
    src_blobs.mkdir(parents=True, exist_ok=True)
    blob_store = BlobStore(src_blobs)

    raw_attachment_bytes = b"PDF_HEADER_CONFIDENTIAL_AUDIT_REPORT_2026\x00\xff"
    write_res = blob_store.put(raw_attachment_bytes)

    Session = get_session_factory()
    test_email = f"drill-{uuid.uuid4().hex[:8]}@example.com"
    with Session() as session:
        acc = create_account(session, email=test_email, provider="imap", config={"host": "mail.test"})
        session.commit()
        acc_id = acc.id

        folder = Folder(account_id=acc_id, remote_id="INBOX", name="收件箱", role="inbox")
        session.add(folder)
        session.commit()

        msg = Message(
            account_id=acc_id,
            remote_id="msg-drill-001",
            subject="恢复演练重要邮件",
            from_address="boss@corp.test",
            sort_time=datetime.now(timezone.utc),
            is_read=True,
            has_attachments=True,
        )
        session.add(msg)
        session.commit()

        body = MessageBody(
            message_id=msg.id,
            text_plain="纯文本邮件正文内容。",
            text_html="<p>HTML邮件正文内容。</p>",
        )
        session.add(body)

        mb = MessageBlob(
            content_sha256=write_res.content_sha256,
            size_bytes=write_res.size_bytes,
            storage_path=write_res.storage_path,
            key_version=write_res.key_version,
            ref_count=1,
        )
        session.add(mb)
        session.commit()

        link = MessageBlobLink(message_id=msg.id, blob_id=mb.id)
        session.add(link)

        att = Attachment(
            message_id=msg.id,
            blob_id=mb.id,
            filename="audit_report.pdf",
            content_type="application/pdf",
            size_bytes=len(raw_attachment_bytes),
        )
        session.add(att)
        session.commit()

    # 2. Run real backup package generation
    backup_out = tmp_path / "backup_out"
    pkg_path = create_backup_package(
        backup_out,
        include_blobs=True,
        encrypt=True,
        database_url_override=source_url,
        blobs_dir=src_blobs,
        allow_dump_stub=False,
    )
    assert pkg_path.is_dir()
    assert (pkg_path / "backup.kkbak").is_file()

    # 3. Verify backup package integrity
    vr = verify_backup_package(pkg_path, env={"MAIL_CORE_BACKUP_KEY": backup_key_b64}, allow_stub=False)
    assert vr.ok is True, vr.errors
    assert vr.members_checked >= 3

    # 4. Create fresh target database
    user, pwd, host, port = _pg_credentials()
    target_db_name = f"kkmail_drill_target_{uuid.uuid4().hex[:12]}"
    admin_url = URL.create("postgresql+psycopg", username=user, password=pwd, host=host, port=port, database="postgres")
    target_url_obj = URL.create(
        "postgresql+psycopg", username=user, password=pwd, host=host, port=port, database=target_db_name
    )
    target_url = target_url_obj.render_as_string(hide_password=False)

    admin_engine = create_engine(admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{target_db_name}"'))

    target_blobs = tmp_path / "target_blobs"

    try:
        # 5. Restore into target database and target blobs
        restore_res = restore_backup_package(
            pkg_path,
            target_database_url=target_url,
            target_blobs_dir=target_blobs,
            keyring=keyring,
            source_database_url=source_url,
            allow_stub=False,
        )
        assert restore_res.ok is True
        assert restore_res.database_restored is True
        assert restore_res.blobs_restored >= 1
        assert restore_res.duration_seconds > 0
        assert restore_res.package_size_bytes > 0

        # 6. Business integrity validation in target database
        target_engine = create_engine(target_url)
        with target_engine.connect() as conn:
            # Account exists
            acc_row = conn.execute(
                text("SELECT email, provider FROM accounts WHERE email = :email"),
                {"email": test_email},
            ).one()
            assert acc_row[0] == test_email
            assert acc_row[1] == "imap"

            # Message exists
            msg_row = conn.execute(
                text("SELECT subject, from_address, is_read FROM messages WHERE remote_id = 'msg-drill-001'")
            ).one()
            assert msg_row[0] == "恢复演练重要邮件"
            assert msg_row[1] == "boss@corp.test"
            assert msg_row[2] is True

            # Body exists
            body_row = conn.execute(text("SELECT text_plain, text_html FROM message_bodies")).one()
            assert "纯文本邮件正文内容" in body_row[0]
            assert "HTML邮件正文内容" in body_row[1]

            # Attachment blob exists in target_blobs and decrypts correctly
            att_row = conn.execute(text("SELECT filename, size_bytes FROM attachments")).one()
            assert att_row[0] == "audit_report.pdf"
            assert att_row[1] == len(raw_attachment_bytes)

            target_blob_store = BlobStore(target_blobs)
            recovered_bytes = target_blob_store.get(write_res.content_sha256)
            assert recovered_bytes == raw_attachment_bytes, "Recovered blob plaintext mismatch"

    finally:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{target_db_name}" WITH (FORCE)'))


# --- AC-003, AC-004: Failure Guards, Tamper & Safety Rejection ---------------------


def test_backup_restore_failure_guards_and_tamper_rejection(tmp_path, monkeypatch):
    """AC-003, AC-004: Rejects bad keys, corrupted files, stub restore, self-overwrite and path traversal."""
    good_key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BACKUP_KEY", good_key)
    keyring = {1: base64.b64decode(good_key)}

    source_url = os.environ["MAIL_CORE_DATABASE_URL"]

    # 1. Refuse restoring onto the same source database (AC-004)
    out_dir = tmp_path / "bak_pkg"
    pkg = create_backup_package(
        out_dir,
        include_blobs=False,
        encrypt=True,
        database_url_override=source_url,
        allow_dump_stub=False,
    )
    with pytest.raises(RuntimeError, match="refusing to restore onto source database"):
        restore_backup_package(
            pkg,
            target_database_url=source_url,
            target_blobs_dir=tmp_path / "blobs",
            keyring=keyring,
            source_database_url=source_url,
        )

    # 2. Refuse path traversal in target blobs dir (AC-004)
    with pytest.raises(RuntimeError, match="path traversal"):
        restore_backup_package(
            pkg,
            target_database_url="postgresql+psycopg://postgres:pw@127.0.0.1:15433/other",
            target_blobs_dir="../escaped_blobs",
            keyring=keyring,
            source_database_url=source_url,
        )

    # 3. Bad key rejection (AC-003)
    wrong_keyring = {1: b"0" * 32}
    with pytest.raises((RuntimeError, BackupCryptoError)):
        restore_backup_package(
            pkg,
            target_database_url="postgresql+psycopg://postgres:pw@127.0.0.1:15433/target_dummy",
            target_blobs_dir=tmp_path / "blobs",
            keyring=wrong_keyring,
            source_database_url=source_url,
        )

    # 4. Tampered package rejection (AC-003)
    corrupted_dir = tmp_path / "corrupted_pkg"
    shutil.copytree(pkg, corrupted_dir)
    kkbak_file = corrupted_dir / "backup.kkbak"
    corrupt_bytes = bytearray(kkbak_file.read_bytes())
    corrupt_bytes[-10] ^= 0xFF
    kkbak_file.write_bytes(corrupt_bytes)

    with pytest.raises((RuntimeError, BackupCryptoError)):
        restore_backup_package(
            corrupted_dir,
            target_database_url="postgresql+psycopg://postgres:pw@127.0.0.1:15433/target_dummy",
            target_blobs_dir=tmp_path / "blobs",
            keyring=keyring,
            source_database_url=source_url,
        )

    # 5. Refuse SQL stub backup package when allow_stub=False (AC-005)
    stub_pkg = create_backup_package(
        tmp_path / "stub_pkg",
        include_blobs=False,
        encrypt=True,
        database_url_override="postgresql://nobody:nope@127.0.0.1:1/none",
        allow_dump_stub=True,
    )
    with pytest.raises((RuntimeError, BackupCryptoError)):
        restore_backup_package(
            stub_pkg,
            target_database_url="postgresql+psycopg://postgres:pw@127.0.0.1:15433/target_dummy",
            target_blobs_dir=tmp_path / "blobs",
            keyring=keyring,
            source_database_url=source_url,
            allow_stub=False,
        )
