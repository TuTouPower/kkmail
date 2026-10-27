#!/usr/bin/env python3
"""Migrate accounts, groups, credentials and emails from legacy SQLite to mail-core PostgreSQL."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


def legacy_account_connection(row) -> tuple[str, dict]:
    """Reject unsupported/missing IMAP configuration before any import writes."""
    from mail_core.accounts.connection import MICROSOFT_DOMAINS, reject_microsoft_imap

    email = row["email"].strip().lower()
    auth_type = (row["authorization_type"] or "").strip().lower()
    if auth_type == "graph":
        return "graph", {}
    if auth_type not in ("", "imap"):
        raise ValueError(
            f"Unknown legacy authorization_type {auth_type!r} for legacy account record "
            f"{row['id']}; set authorization_type to 'graph' or 'imap' explicitly "
            "before migrating"
        )
    if auth_type == "" and row["refresh_token"]:
        domain = email.rsplit("@", 1)[-1].rstrip(".") if "@" in email else ""
        if domain in MICROSOFT_DOMAINS:
            return "graph", {}
        raise ValueError(
            f"Legacy account record {row['id']} has a refresh_token but email domain "
            f"{domain!r} is not a known Microsoft domain and authorization_type is not "
            "'graph'; set authorization_type explicitly so the operator decides the provider"
        )
    config = {"imap_host": row["imap_host"] or "", "imap_port": row["imap_port"] or 993, "use_ssl": True}
    reject_microsoft_imap(email, config)
    if not config["imap_host"]:
        raise ValueError(f"IMAP server missing for legacy account record {row['id']}")
    return "imap", config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate accounts, groups, credentials and emails from legacy SQLite to mail-core PostgreSQL."
    )
    parser.add_argument("--source", required=True, type=Path, help="legacy SQLite database path")
    parser.add_argument(
        "--target-url",
        default=None,
        help="PostgreSQL target URL without a password; password-bearing URLs must be "
        "passed via --target-url-env or MAIL_CORE_DATABASE_URL so the secret stays "
        "out of the process list and shell history",
    )
    parser.add_argument(
        "--target-url-env",
        default=None,
        metavar="VAR",
        help="name of the environment variable holding the PostgreSQL target URL",
    )
    parser.add_argument("--yes", action="store_true", help="confirm the displayed source and target")
    return parser.parse_args(argv)


# Parse CLI arguments early so --help succeeds without heavy imports or DB connection
_cli_args = parse_args() if __name__ == "__main__" else None

import base64
import binascii
import email.utils
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime

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
_LEGACY_GROUP_NAME_MAX_LENGTH = 128


def _legacy_group_target_name(name: str, legacy_id: int) -> str:
    suffix = f" (legacy group {legacy_id})"
    prefix = name[:_LEGACY_GROUP_NAME_MAX_LENGTH - len(suffix)].rstrip()
    return f"{prefix}{suffix}"


def _legacy_group_target_names(legacy_groups: list[sqlite3.Row]) -> dict[int, str]:
    name_counts = Counter(group["name"] for group in legacy_groups)
    return {
        group["id"]: (
            _legacy_group_target_name(group["name"], group["id"])
            if name_counts[group["name"]] > 1
            else group["name"]
        )
        for group in legacy_groups
    }


def _update_account_from_legacy(
    account: Account,
    *,
    provider: str,
    credential_ref: str,
    display_name: str,
    config: dict[str, object],
    group_id: uuid.UUID | None,
    sync_enabled: bool,
) -> None:
    """Converge source-owned fields while preserving runtime status and sidebar order."""
    account.provider = provider
    account.credential_ref = credential_ref
    account.display_name = display_name
    account.config = config
    account.group_id = group_id
    account.sync_enabled = sync_enabled


class MigrationError(RuntimeError):
    """Base exception for migration failures."""


class MigrationDecryptionError(MigrationError):
    """Raised when decrypting a legacy encrypted field fails."""


@dataclass(frozen=True, slots=True)
class MessageMigrationReport:
    migrated: int = 0
    skipped_existing: int = 0
    imported_without_remote_id: int = 0
    legacy_total: int = 0
    flag_state_unavailable: int = 0
    read_state_unavailable: int = 0
    attachment_state_unavailable: int = 0


def _legacy_flag_value(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        return None
    return bool(value)


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


_RETAINED_MESSAGE_BATCH_SIZE = 1000


def _commit_message_batch(session) -> None:
    """Commit one message batch and release its identity-map entries.

    Duck-typed so lightweight session doubles without commit/expunge
    (unit-test fakes) keep working; real sessions always take both calls.
    """
    commit = getattr(session, "commit", None)
    if callable(commit):
        commit()
    expunge_all = getattr(session, "expunge_all", None)
    if callable(expunge_all):
        expunge_all()


def migrate_retained_messages(
    session,
    sqlite_cursor: sqlite3.Cursor,
    *,
    account_id_map: dict[int, uuid.UUID],
    folder_id_map: dict[uuid.UUID, uuid.UUID],
    batch_size: int = _RETAINED_MESSAGE_BATCH_SIZE,
) -> MessageMigrationReport:
    """Import retained messages from a read-only legacy SQLite cursor.

    Commits and expunges every ``batch_size`` processed rows so a large
    legacy database neither holds one transaction/lock for the whole run
    nor keeps every migrated Message in the identity map; report counts
    accumulate across batches. The caller still commits the final partial
    batch (together with any follow-up work in the same session).
    """
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    migrated = 0
    skipped_existing = 0
    imported_without_remote_id = 0
    flag_state_unavailable = 0
    read_state_unavailable = 0
    attachment_state_unavailable = 0
    legacy_columns = {
        str(row[1]).lower(): str(row[1])
        for row in sqlite_cursor.execute("PRAGMA table_info(retained_normal_mail_messages)").fetchall()
    }
    flag_column = next(
        (
            legacy_columns[name]
            for name in ("is_flagged", "is_starred", "flagged", "starred")
            if name in legacy_columns
        ),
        None,
    )
    legacy_total = int(
        sqlite_cursor.execute("SELECT COUNT(*) FROM retained_normal_mail_messages").fetchone()[0]
    )
    legacy_msgs = sqlite_cursor.execute("SELECT * FROM retained_normal_mail_messages ORDER BY id DESC")

    processed_in_batch = 0

    def note_processed_row() -> None:
        nonlocal processed_in_batch
        processed_in_batch += 1
        if processed_in_batch >= batch_size:
            _commit_message_batch(session)
            processed_in_batch = 0

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
            note_processed_row()
            continue

        subject = legacy_msg["subject"] if legacy_msg["subject"] else ""
        sender = legacy_msg["sender"] if legacy_msg["sender"] else ""
        from_address, from_name = _legacy_sender(sender)
        body = legacy_msg["body"] if legacy_msg["body"] else ""
        body_type = legacy_msg["body_type"]
        is_html = body_type == "html"
        is_flagged = _legacy_flag_value(legacy_msg[flag_column]) if flag_column else None
        if is_flagged is None:
            flag_state_unavailable += 1
        is_read_value = _legacy_flag_value(legacy_msg["is_read"])
        if is_read_value is None:
            read_state_unavailable += 1
        has_attachments_value = _legacy_flag_value(legacy_msg["has_attachments"])
        if has_attachments_value is None:
            attachment_state_unavailable += 1

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
            is_read=is_read_value or False,
            is_flagged=is_flagged,
            has_attachments=has_attachments_value or False,
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
        note_processed_row()

    return MessageMigrationReport(
        migrated=migrated,
        skipped_existing=skipped_existing,
        imported_without_remote_id=imported_without_remote_id,
        legacy_total=legacy_total,
        flag_state_unavailable=flag_state_unavailable,
        read_state_unavailable=read_state_unavailable,
        attachment_state_unavailable=attachment_state_unavailable,
    )


def _load_blob_keyring(blob_b64: str) -> Keyring:
    """Validate MAIL_CORE_BLOB_KEY_V1 once, up front, with an operator-facing error."""
    try:
        blob_raw = base64.b64decode(blob_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            "MAIL_CORE_BLOB_KEY_V1 must contain valid base64 encoding a 32-byte key"
        ) from exc
    if len(blob_raw) != 32:
        raise ValueError(
            "MAIL_CORE_BLOB_KEY_V1 must encode exactly 32 bytes "
            f"(decoded {len(blob_raw)} bytes); generate one with: "
            "python3 -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())'"
        )
    return Keyring({1: blob_raw}, active_version=1)


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


def _resolve_target_url(args: argparse.Namespace, environ: dict | None = None) -> str:
    """Resolve the target URL without ever requiring a password on argv.

    Priority: --target-url-env VAR, then a passwordless --target-url, then
    the MAIL_CORE_DATABASE_URL environment fallback.
    """
    if environ is None:
        environ = os.environ
    env_var = getattr(args, "target_url_env", None)
    if env_var:
        value = environ.get(env_var)
        if not value:
            raise ValueError(
                f"environment variable {env_var} named by --target-url-env is not set or is empty"
            )
        return value
    cli_url = getattr(args, "target_url", None)
    if cli_url:
        from sqlalchemy.engine import make_url

        try:
            parsed = make_url(cli_url)
        except Exception as exc:
            raise ValueError("invalid PostgreSQL target URL") from exc
        if parsed.password:
            raise ValueError(
                "--target-url must not contain a password (it would be exposed in the "
                "process list and shell history); pass the URL via --target-url-env VAR "
                "or MAIL_CORE_DATABASE_URL instead"
            )
        return cli_url
    fallback = environ.get("MAIL_CORE_DATABASE_URL")
    if fallback:
        return fallback
    raise ValueError(
        "a target URL is required: pass a passwordless --target-url, "
        "--target-url-env VAR, or set MAIL_CORE_DATABASE_URL"
    )


def _target_url_details(raw_url: str) -> tuple[str, str]:
    from sqlalchemy.engine import make_url

    try:
        url = make_url(raw_url)
    except Exception as exc:
        raise ValueError("invalid PostgreSQL target URL") from exc
    if url.drivername not in ("postgresql", "postgresql+psycopg") or not url.host or not url.database:
        raise ValueError("target URL must identify a PostgreSQL host and database")
    normalized_url = url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    host = f"[{url.host}]" if ":" in url.host else url.host
    target = f"host={host} port={url.port or 5432} database={url.database}"
    return normalized_url, target


def main(args: argparse.Namespace) -> int:
    sqlite_path = args.source.expanduser().resolve()
    try:
        target_url, target_summary = _target_url_details(_resolve_target_url(args))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Source SQLite: {sqlite_path}")
    print(f"Target PostgreSQL: {target_summary}")
    if not args.yes:
        print("No writes performed; review the target and rerun with --yes.", file=sys.stderr)
        return 2
    if not sqlite_path.is_file():
        print(f"Legacy SQLite database not found: {sqlite_path}", file=sys.stderr)
        return 1

    migrate(sqlite_path, target_url)
    return 0


def migrate(sqlite_path: Path, target_url: str) -> None:

    legacy_secret = os.environ.get("LEGACY_SECRET_KEY")
    if not legacy_secret:
        print("LEGACY_SECRET_KEY required", file=sys.stderr)
        sys.exit(1)
    legacy_cipher = get_legacy_cipher(legacy_secret)

    blob_b64 = os.environ.get("MAIL_CORE_BLOB_KEY_V1")
    if not blob_b64:
        print("MAIL_CORE_BLOB_KEY_V1 required", file=sys.stderr)
        sys.exit(1)

    try:
        keyring = _load_blob_keyring(blob_b64)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    Session = get_session_factory(target_url)
    sqlite_conn = sqlite3.connect(f"{sqlite_path.as_uri()}?mode=ro", uri=True)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    legacy_accounts = sqlite_cursor.execute("SELECT * FROM accounts").fetchall()
    for legacy_account in legacy_accounts:
        legacy_account_connection(legacy_account)

    print("=== 1. Migrating Groups ===")
    group_id_map: dict[int, uuid.UUID] = {}
    with Session() as session:
        legacy_groups = sqlite_cursor.execute(
            "SELECT id, name, color, sort_order FROM groups ORDER BY id"
        ).fetchall()
        target_names = _legacy_group_target_names(legacy_groups)
        for g in legacy_groups:
            target_name = target_names[g["id"]]
            color = g["color"] or "#1a1a1a"
            sort_order = g["sort_order"] or 0
            if target_name != g["name"]:
                print(
                    f"Warning: duplicate legacy group name {g['name']!r}; "
                    f"preserving group id {g['id']} as {target_name!r}.",
                    file=sys.stderr,
                )
                existing = session.query(AccountGroup).filter_by(name=target_name).first()
            else:
                existing = session.query(AccountGroup).filter_by(
                    name=target_name,
                    color=color,
                    sort_order=sort_order,
                ).first()
                if existing is None:
                    name_conflict = session.query(AccountGroup).filter_by(name=target_name).first()
                    if name_conflict is not None:
                        target_name = _legacy_group_target_name(g["name"], g["id"])
                        print(
                            f"Warning: target group name collision {g['name']!r}; "
                            f"preserving legacy group id {g['id']} as {target_name!r}.",
                            file=sys.stderr,
                        )
                        existing = session.query(AccountGroup).filter_by(name=target_name).first()
            if existing:
                if target_name != g["name"] and (existing.color != color or existing.sort_order != sort_order):
                    print(
                        f"Warning: preserving existing metadata for legacy group id {g['id']}.",
                        file=sys.stderr,
                    )
                group_id_map[g["id"]] = existing.id
            else:
                new_group_id = uuid.uuid4()
                ag = AccountGroup(
                    id=new_group_id,
                    name=target_name,
                    color=color,
                    sort_order=sort_order,
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

            for a in legacy_accounts:
                email_norm = a["email"].strip().lower()
                existing = session.query(Account).filter_by(email=email_norm).first()

                provider, cfg = legacy_account_connection(a)

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
                    _update_account_from_legacy(
                        existing,
                        provider=provider,
                        credential_ref=ref,
                        display_name=a["remark"] or email_norm,
                        config=cfg,
                        group_id=group_id,
                        sync_enabled=bool(a["status"] == "active"),
                    )

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

    print("=== 3. Migrating Retained Messages ===")
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
    print(
        f"Legacy retained message rows: {message_report.legacy_total}; "
        f"migrated: {message_report.migrated}; already present: {message_report.skipped_existing}."
    )
    if message_report.imported_without_remote_id:
        print(
            "Imported "
            f"{message_report.imported_without_remote_id} messages without canonical provider remote IDs."
        )
    if message_report.flag_state_unavailable:
        print(
            "Flagged state unavailable for "
            f"{message_report.flag_state_unavailable} migrated messages."
        )
    if message_report.read_state_unavailable:
        print(
            "Read state unavailable for "
            f"{message_report.read_state_unavailable} migrated messages (defaulted to unread)."
        )
    if message_report.attachment_state_unavailable:
        print(
            "Attachment state unavailable for "
            f"{message_report.attachment_state_unavailable} migrated messages "
            "(defaulted to no attachments)."
        )
    print("MIGRATION COMPLETED SUCCESSFULLY.")
    sqlite_conn.close()


if __name__ == "__main__":
    raise SystemExit(main(_cli_args))
