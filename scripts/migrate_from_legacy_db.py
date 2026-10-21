#!/usr/bin/env python3
"""Migrate accounts, groups, credentials and emails from legacy SQLite to mail-core PostgreSQL."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add src to sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from mail_core.accounts.credentials import DbCredentialStore, save_json_secret
from mail_core.blobs.crypto import Keyring
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import (
    Account,
    AccountGroup,
    Folder,
    FolderStats,
    Message,
    MessageBody,
    MessageLocation,
    MessageSearch,
)


def get_legacy_cipher(secret_key: str) -> Fernet:
    salt = b"outlook_email_encryption_salt_v1"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return Fernet(key)


def decrypt_legacy_field(cipher: Fernet, val: str | None) -> str:
    if not val:
        return ""
    if val.startswith("enc:"):
        try:
            return cipher.decrypt(val[4:].encode("utf-8")).decode("utf-8")
        except Exception:
            return ""
    return val


def migrate():
    sqlite_path = ROOT / "data" / "outlook_accounts.db"
    if not sqlite_path.is_file():
        print(f"Legacy sqlite db not found: {sqlite_path}", file=sys.stderr)
        sys.exit(1)

    legacy_secret = os.environ.get("LEGACY_SECRET_KEY")
    if not legacy_secret:
        print("LEGACY_SECRET_KEY required", file=sys.stderr)
        sys.exit(1)
    legacy_cipher = get_legacy_cipher(legacy_secret)

    blob_b64 = os.environ.get("MAIL_CORE_BLOB_KEY_V1")
    if not blob_b64:
        print("MAIL_CORE_BLOB_KEY_V1 required", file=sys.stderr)
        sys.exit(1)

    blob_raw = base64.b64decode(blob_b64)
    keyring = Keyring({1: blob_raw}, active_version=1)

    Session = get_session_factory()
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    print("=== 1. Migrating Groups ===")
    group_id_map: dict[int, uuid.UUID] = {}
    with Session() as session:
        legacy_groups = sqlite_cursor.execute("SELECT id, name, color, sort_order FROM groups").fetchall()
        for g in legacy_groups:
            existing = session.query(AccountGroup).filter_by(name=g["name"]).first()
            if existing:
                group_id_map[g["id"]] = existing.id
            else:
                new_group_id = uuid.uuid4()
                ag = AccountGroup(
                    id=new_group_id,
                    name=g["name"],
                    color=g["color"] or "#1a1a1a",
                    sort_order=g["sort_order"] or 0,
                )
                session.add(ag)
                group_id_map[g["id"]] = new_group_id
        session.commit()
    print(f"Migrated {len(group_id_map)} groups.")

    print("=== 2. Migrating Accounts & Credentials ===")
    account_id_map: dict[int, uuid.UUID] = {}
    folder_id_map: dict[uuid.UUID, uuid.UUID] = {}

    with Session() as session:
        cred_store = DbCredentialStore(keyring=keyring, session_factory=lambda: session)

        legacy_accounts = sqlite_cursor.execute("SELECT * FROM accounts").fetchall()
        for a in legacy_accounts:
            email_norm = a["email"].strip().lower()
            existing = session.query(Account).filter_by(email=email_norm).first()

            auth_type = (a["authorization_type"] or "").lower()
            if auth_type == "graph":
                provider = "graph"
            elif auth_type == "imap":
                provider = "imap"
            else:
                provider = "imap"

            cfg: dict = {}
            if provider == "imap":
                cfg = {
                    "imap_host": a["imap_host"] or "outlook.office365.com",
                    "imap_port": a["imap_port"] or 993,
                    "use_ssl": True,
                }

            group_id = group_id_map.get(a["group_id"])
            ref = f"account:{email_norm}"

            if not existing:
                acc_id = uuid.uuid4()
                acc = Account(
                    id=acc_id,
                    email=email_norm,
                    provider=provider,
                    credential_ref=ref,
                    display_name=a["remark"] or email_norm,
                    config=cfg,
                    group_id=group_id,
                    sync_status="idle",
                    sync_enabled=bool(a["status"] == "active"),
                )
                session.add(acc)
                session.flush()
                account_id_map[a["id"]] = acc_id
            else:
                acc_id = existing.id
                account_id_map[a["id"]] = acc_id

            # Save credentials into DbCredentialStore
            if provider == "graph":
                cid = a["client_id"] or ""
                rt = decrypt_legacy_field(legacy_cipher, a["refresh_token"])
                creds = {"client_id": cid, "refresh_token": rt}
                save_json_secret(cred_store, ref, creds)
            else:
                pwd = decrypt_legacy_field(legacy_cipher, a["password"] or a["imap_password"])
                creds = {"password": pwd}
                save_json_secret(cred_store, ref, creds)

            # Ensure INBOX folder exists
            inbox_folder = session.query(Folder).filter_by(account_id=acc_id, role="inbox").first()
            if not inbox_folder:
                inbox_folder = Folder(account_id=acc_id, remote_id="INBOX", name="INBOX", role="inbox")
                session.add(inbox_folder)
                session.flush()
            folder_id_map[acc_id] = inbox_folder.id

        session.commit()
    print(f"Migrated {len(account_id_map)} accounts with encrypted credentials.")

    print("=== 3. Migrating Retained Messages (Sample / Recent) ===")
    migrated_msgs = 0
    with Session() as session:
        # Migrate recent up to 200 normal messages
        legacy_msgs = sqlite_cursor.execute(
            "SELECT * FROM retained_normal_mail_messages ORDER BY id DESC LIMIT 200"
        ).fetchall()
        now = datetime.now(timezone.utc)

        for m in legacy_msgs:
            old_acc_id = m["account_id"]
            new_acc_id = account_id_map.get(old_acc_id)
            if not new_acc_id:
                continue

            inbox_fid = folder_id_map.get(new_acc_id)
            if not inbox_fid:
                continue

            remote_id = f"legacy-{m['provider_message_id'] or m['id']}"
            existing_msg = session.query(Message).filter_by(account_id=new_acc_id, remote_id=remote_id).first()
            if existing_msg:
                continue

            msg_id = uuid.uuid4()
            subject = m["subject"] or "无主题"
            sender = m["sender"] or "未知发件人"
            body = m["body"] or ""
            is_html = m["body_type"] == "html" or "<html" in body.lower() or "<div" in body.lower()

            msg = Message(
                id=msg_id,
                account_id=new_acc_id,
                remote_id=remote_id,
                subject=subject,
                from_address=sender,
                from_name=sender.split("<")[0].strip() if "<" in sender else sender,
                to_addresses=[m["recipients"]] if m["recipients"] else [],
                sort_time=now,
                is_read=bool(m["is_read"]),
                is_flagged=False,
                has_attachments=bool(m["has_attachments"]),
                snippet=m["body_preview"] or (body[:120] if body else ""),
            )
            session.add(msg)
            session.flush()

            session.add(MessageLocation(message_id=msg_id, folder_id=inbox_fid, uid=m["id"]))
            session.add(
                MessageBody(
                    message_id=msg_id,
                    text_html=body if is_html else None,
                    text_plain=body if not is_html else None,
                )
            )
            session.add(
                MessageSearch(
                    message_id=msg_id,
                    account_id=new_acc_id,
                    subject=subject,
                    from_text=sender,
                    body_text=body[:2000] if body else "",
                )
            )
            migrated_msgs += 1

        # Recompute folder stats
        for acc_id, fid in folder_id_map.items():
            tot = session.query(MessageLocation).filter_by(folder_id=fid).count()
            unr = (
                session.query(Message)
                .join(MessageLocation, MessageLocation.message_id == Message.id)
                .filter(MessageLocation.folder_id == fid, Message.is_read == False)
                .count()
            )
            st = session.query(FolderStats).filter_by(folder_id=fid).first()
            if not st:
                session.add(FolderStats(folder_id=fid, total_count=tot, unread_count=unr))
            else:
                st.total_count = tot
                st.unread_count = unr

        session.commit()
    print(f"Migrated {migrated_msgs} messages into PostgreSQL.")
    print("MIGRATION COMPLETED SUCCESSFULLY.")


if __name__ == "__main__":
    migrate()
