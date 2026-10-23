#!/usr/bin/env python3
"""Migrate accounts, groups, credentials and emails from legacy SQLite to mail-core PostgreSQL."""

from __future__ import annotations

import argparse
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate accounts, groups, credentials and emails from legacy SQLite to mail-core PostgreSQL."
    )
    return parser.parse_args(argv)


# Parse CLI arguments early so --help succeeds without heavy imports or DB connection
if __name__ == "__main__":
    parse_args()

import base64
import email.utils
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
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

_MAX_POSTGRES_BIGINT = (1 << 63) - 1
_MAX_POSTGRES_BIGINT_TEXT = str(_MAX_POSTGRES_BIGINT)


class MigrationError(RuntimeError):
    """Base exception for migration failures."""


class MigrationDecryptionError(MigrationError):
    """Raised when decrypting a legacy encrypted field fails."""


@dataclass(frozen=True, slots=True)
class MessageMigrationReport:
    migrated: int = 0
    skipped_existing: int = 0
    imported_without_remote_id: int = 0


def _legacy_sender(raw: str | None) -> tuple[str, str | None]:
    if not raw:
        return "", None
    for name, address in email.utils.getaddresses([raw]):
        if address and "@" in address:
            return address, name or None
    return "", raw


def _legacy_addresses(raw: str | None) -> list[str]:
    return [address for _name, address in email.utils.getaddresses([raw or ""]) if address]


def _legacy_received_time(id_mode: str | None, raw: str | None) -> datetime | None:
    if str(id_mode or "").strip().lower() != "graph" or not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _legacy_uid(id_mode: str | None, provider_message_id: str | None) -> int | None:
    if str(id_mode or "").strip().lower() != "uid" or isinstance(provider_message_id, bool):
        return None
    value = str(provider_message_id or "").strip()
    if not value or not value.isascii() or not value.isdecimal():
        return None
    normalized = value.lstrip("0")
    if not normalized:
        return None
    if len(normalized) > len(_MAX_POSTGRES_BIGINT_TEXT) or (
        len(normalized) == len(_MAX_POSTGRES_BIGINT_TEXT)
        and normalized > _MAX_POSTGRES_BIGINT_TEXT
    ):
        return None
    uid = int(normalized)
    return uid if 0 < uid <= _MAX_POSTGRES_BIGINT else None


def migrate_retained_messages(
    session,
    sqlite_cursor: sqlite3.Cursor,
    *,
    account_id_map: dict[int, uuid.UUID],
    folder_id_map: dict[uuid.UUID, uuid.UUID],
) -> MessageMigrationReport:
    """Import retained messages from a read-only legacy SQLite cursor."""
    migrated = 0
    skipped_existing = 0
    imported_without_remote_id = 0
    legacy_msgs = sqlite_cursor.execute(
        "SELECT * FROM retained_normal_mail_messages ORDER BY id DESC LIMIT 200"
    ).fetchall()

    for legacy_msg in legacy_msgs:
        new_account_id = account_id_map.get(legacy_msg["account_id"])
        folder_id = folder_id_map.get(new_account_id) if new_account_id else None
        if not new_account_id or not folder_id:
            continue

        provider_message_id = legacy_msg["provider_message_id"]
        id_mode = str(legacy_msg["id_mode"] or "").strip().lower()
        provider_id = str(provider_message_id or "")
        # Legacy Graph IDs are canonical; IMAP lacks UIDVALIDITY and other modes
        # cannot be addressed safely by mail-core, so keep their identity unknown.
        remote_id = provider_id if id_mode == "graph" and provider_id.strip() else None
        # SQLite id is a local source key used only for stable Message.id, never remote_id/UID.
        msg_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"kkmail:legacy-retained:{new_account_id}:{legacy_msg['id']}",
        )
        if session.get(Message, msg_id) is not None or (
            remote_id is not None
            and session.query(Message).filter_by(account_id=new_account_id, remote_id=remote_id).first()
        ):
            skipped_existing += 1
            continue

        subject = legacy_msg["subject"] if legacy_msg["subject"] else ""
        sender = legacy_msg["sender"] if legacy_msg["sender"] else ""
        from_address, from_name = _legacy_sender(sender)
        body = legacy_msg["body"] if legacy_msg["body"] else ""
        body_type = legacy_msg["body_type"]
        is_html = body_type == "html"

        msg = Message(
            id=msg_id,
            account_id=new_account_id,
            remote_id=remote_id,
            subject=subject,
            from_address=from_address,
            from_name=from_name,
            to_addresses=_legacy_addresses(legacy_msg["recipients"]),
            cc_addresses=_legacy_addresses(legacy_msg["cc"]),
            sort_time=_legacy_received_time(legacy_msg["id_mode"], legacy_msg["received_at"]),
            is_read=bool(legacy_msg["is_read"]),
            is_flagged=None,
            has_attachments=bool(legacy_msg["has_attachments"]),
            snippet=legacy_msg["body_preview"],
        )
        session.add(msg)
        session.flush()
        session.add(
            MessageLocation(
                message_id=msg_id,
                folder_id=folder_id,
                uid=_legacy_uid(legacy_msg["id_mode"], provider_message_id),
            )
        )
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
                account_id=new_account_id,
                subject=subject,
                from_text=sender,
                body_text=body[:2000] if body else "",
            )
        )
        migrated += 1
        if remote_id is None:
            imported_without_remote_id += 1

    return MessageMigrationReport(
        migrated=migrated,
        skipped_existing=skipped_existing,
        imported_without_remote_id=imported_without_remote_id,
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


def decrypt_legacy_field(
    cipher: Fernet,
    val: str | None,
    *,
    record_id: str | int | None = None,
    field_name: str | None = None,
) -> str:
    if not val:
        return ""
    if val.startswith("enc:"):
        try:
            return cipher.decrypt(val[4:].encode("utf-8")).decode("utf-8")
        except Exception as exc:
            context = (
                f" (record_id={record_id!r}, field={field_name!r})"
                if record_id is not None or field_name is not None
                else ""
            )
            raise MigrationDecryptionError(f"Failed to decrypt legacy field{context}") from exc
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
    sqlite_conn = sqlite3.connect(f"{sqlite_path.as_uri()}?mode=ro", uri=True)
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
        try:
            cred_store = DbCredentialStore(keyring=keyring, session_factory=lambda: session)

            legacy_accounts = sqlite_cursor.execute("SELECT * FROM accounts").fetchall()
            for a in legacy_accounts:
                email_norm = a["email"].strip().lower()
                existing = session.query(Account).filter_by(email=email_norm).first()

                auth_type = (a["authorization_type"] or "").lower()
                has_refresh_token = bool(a["refresh_token"])
                if auth_type == "graph" or (has_refresh_token and "outlook" in email_norm):
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

                # Save credentials into DbCredentialStore before creating/updating records
                if provider == "graph":
                    cid = a["client_id"] or ""
                    rt = decrypt_legacy_field(
                        legacy_cipher,
                        a["refresh_token"],
                        record_id=a["id"],
                        field_name="refresh_token",
                    )
                    if not rt:
                        raise MigrationDecryptionError(
                            f"Missing required decrypted credential (record_id={a['id']!r}, field='refresh_token')"
                        )
                    creds = {"client_id": cid, "refresh_token": rt}
                else:
                    raw_pwd = a["password"] or a["imap_password"]
                    pwd_field = "password" if a["password"] else "imap_password"
                    pwd = decrypt_legacy_field(
                        legacy_cipher,
                        raw_pwd,
                        record_id=a["id"],
                        field_name=pwd_field,
                    )
                    if not pwd:
                        raise MigrationDecryptionError(
                            f"Missing required decrypted credential (record_id={a['id']!r}, field={pwd_field!r})"
                        )
                    creds = {"password": pwd}

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

                save_json_secret(cred_store, ref, creds)

                # Ensure INBOX folder exists
                inbox_folder = session.query(Folder).filter_by(account_id=acc_id, role="inbox").first()
                if not inbox_folder:
                    inbox_folder = Folder(account_id=acc_id, remote_id="INBOX", name="INBOX", role="inbox")
                    session.add(inbox_folder)
                    session.flush()
                folder_id_map[acc_id] = inbox_folder.id

            session.commit()
        except Exception:
            session.rollback()
            raise
    print(f"Migrated {len(account_id_map)} accounts with encrypted credentials.")

    print("=== 3. Migrating Retained Messages (Sample / Recent) ===")
    with Session() as session:
        message_report = migrate_retained_messages(
            session,
            sqlite_cursor,
            account_id_map=account_id_map,
            folder_id_map=folder_id_map,
        )

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
    print(f"Migrated {message_report.migrated} messages into PostgreSQL.")
    if message_report.imported_without_remote_id:
        print(
            "Imported "
            f"{message_report.imported_without_remote_id} messages without canonical provider remote IDs."
        )
    print("MIGRATION COMPLETED SUCCESSFULLY.")
    sqlite_conn.close()


if __name__ == "__main__":
    migrate()
