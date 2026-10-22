"""Deterministic artificial mail, with real encrypted MIME and attachment blobs."""

from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from uuid import NAMESPACE_URL, uuid5

from mail_core.blobs.store import BlobStore
from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import (
    Account, Attachment, Folder, Message, MessageBlob, MessageBlobLink,
    MessageBody, MessageLocation,
)
from mail_core.search.index import upsert_message_search

SORT_TIME = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def fixture_id(seed, key):
    return uuid5(NAMESPACE_URL, f"kkmail-test:{seed}:{key}")


def mime_message(seed, account, index):
    message = EmailMessage(policy=SMTP)
    message["From"] = "测试发件人 <sender@example.test>"
    message["To"] = f"account-{account}@example.test"
    message["Subject"] = f"测试邮件 {seed}-{index}"
    message["Message-ID"] = f"<fixture-{seed}-{index}@example.test>"
    message["Date"] = format_datetime(SORT_TIME)
    message.set_content(f"正文 {seed}-{account}-{index}")
    message.add_alternative(f"<p>正文 {seed}-{account}-{index}</p>", subtype="html")
    attachment = f"附件 {seed}-{account}-{index}".encode()
    message.add_attachment(attachment, maintype="application", subtype="octet-stream", filename="测试附件.bin")
    message.set_boundary(f"mixed-{seed}-{account}-{index}")
    message.get_payload()[0].set_boundary(f"alternative-{seed}-{account}-{index}")
    return message.as_bytes(), attachment


def build_mailbox(session, blob_root, *, seed=17, accounts=2, messages_per_account=5):
    store = BlobStore(blob_root)
    result = {"accounts": [], "inboxes": [], "empty_folders": [], "messages": [], "attachments": []}
    for account_index in range(accounts):
        account = Account(id=fixture_id(seed, f"account:{account_index}"),
                          email=f"seed-{seed}-account-{account_index}@example.test", provider="memory")
        session.add(account)
        session.flush()
        inbox = Folder(id=fixture_id(seed, f"inbox:{account_index}"), account_id=account.id,
                       remote_id="INBOX", name="收件箱", role="inbox")
        empty = Folder(id=fixture_id(seed, f"empty:{account_index}"), account_id=account.id,
                       remote_id="EMPTY", name="空目录", role="other")
        session.add_all([inbox, empty])
        session.flush()
        result["accounts"].append(account.id)
        result["inboxes"].append(inbox.id)
        result["empty_folders"].append(empty.id)
        for index in range(messages_per_account):
            raw, attachment = mime_message(seed, account_index, index)
            message = Message(id=fixture_id(seed, f"message:{account_index}:{index}"), account_id=account.id,
                              remote_id=str(index), internet_message_id=f"<fixture-{seed}-{index}@example.test>",
                              subject=f"测试邮件 {seed}-{index}", from_address="sender@example.test",
                              sort_time=SORT_TIME, is_read=index % 2 == 0, has_attachments=True)
            session.add(message)
            session.flush()
            session.add_all([
                MessageLocation(message_id=message.id, folder_id=inbox.id, uid=index + 1),
                MessageBody(message_id=message.id, text_plain=f"正文 {seed}-{account_index}-{index}",
                            text_html=f"<p>正文 {seed}-{account_index}-{index}</p>"),
            ])
            blobs = []
            for payload in (raw, attachment):
                written = store.put(payload)
                blob = MessageBlob(content_sha256=written.content_sha256, key_version=written.key_version,
                                   size_bytes=written.size_bytes, storage_path=written.storage_path)
                session.add(blob)
                session.flush()
                blobs.append(blob)
            session.add_all([
                MessageBlobLink(message_id=message.id, blob_id=blobs[0].id),
                Attachment(message_id=message.id, blob_id=blobs[1].id, part_id="2", filename="测试附件.bin",
                           content_type="application/octet-stream", size_bytes=len(attachment)),
            ])
            upsert_message_search(session, message_id=message.id, body_text=f"正文 {seed}-{account_index}-{index}")
            result["messages"].append(message.id)
            result["attachments"].append((blobs[1].content_sha256, attachment))
        session.flush()
        recompute_folder_stats(session, inbox.id)
        recompute_folder_stats(session, empty.id)
    session.flush()
    return result
