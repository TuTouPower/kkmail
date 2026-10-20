"""Medium findings: IMAP FETCH, Gmail/Graph MIME, jobs ownership, soft quota, scripts/compose."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mail_core.mail.domain.enums import JobStatus
from mail_core.providers.gmail import GmailProvider
from mail_core.providers.graph import GraphProvider
from mail_core.providers.imap import ImapProvider
from mail_core.sync.jobs import JobOwnershipError, complete_job, fail_job


class _FakeSession:
    def flush(self):
        return None


def test_gmail_raw_mime_pads_only_as_needed():
    raw = base64.urlsafe_b64encode(b"hello-mime").decode().rstrip("=")
    assert len(raw) % 4 != 0

    def transport(method, path, params):
        return {"raw": raw}

    assert GmailProvider(credential_ref="x", transport=transport).fetch_mime("m1") == b"hello-mime"

    padded = raw + "=" * ((4 - len(raw) % 4) % 4)

    def transport2(method, path, params):
        return {"raw": padded}

    assert GmailProvider(credential_ref="x", transport=transport2).fetch_mime("m1") == b"hello-mime"


def test_gmail_raw_mime_missing_raises():
    def transport(method, path, params):
        return {}

    with pytest.raises(RuntimeError, match="missing raw MIME"):
        GmailProvider(credential_ref="x", transport=transport).fetch_mime("m1")


def test_graph_fetch_mime_missing_raw_bytes_raises():
    def transport(method, path, params):
        return {"value": "nope"}

    with pytest.raises(RuntimeError, match="missing MIME"):
        GraphProvider(credential_ref="x", transport=transport).fetch_mime("x")


def test_graph_fetch_mime_accepts_bytes_or_raw_bytes():
    def t_bytes(method, path, params):
        return b"mime-bytes"

    assert GraphProvider(credential_ref="x", transport=t_bytes).fetch_mime("x") == b"mime-bytes"

    def t_dict(method, path, params):
        return {"raw_bytes": b"from-dict"}

    assert GraphProvider(credential_ref="x", transport=t_dict).fetch_mime("x") == b"from-dict"


def test_imap_timeout_passed_to_connect(monkeypatch):
    seen = {}

    class FakeIMAP:
        def __init__(self, host, port, timeout=None, ssl_context=None):
            seen["timeout"] = timeout
            seen["host"] = host
            seen["ssl_context"] = ssl_context

        def login(self, *a):
            return ("OK", [b""])

        def logout(self):
            return ("OK", [b""])

        def list(self):
            return ("NO", [b"fail"])

    monkeypatch.setattr("mail_core.providers.imap.imaplib.IMAP4_SSL", FakeIMAP)
    p = ImapProvider(host="h", port=993, username="u", password="p", timeout=12.5)
    with pytest.raises(RuntimeError, match="LIST failed"):
        p.list_folders()
    assert seen["timeout"] == 12.5
    assert seen["ssl_context"] is not None


def test_imap_fetch_failure_raises_not_advance(monkeypatch):
    class FakeIMAP:
        def __init__(self, *a, **k):
            pass

        def login(self, *a):
            return ("OK", [b""])

        def logout(self):
            return ("OK", [b""])

        def select(self, *a, **k):
            return ("OK", [b"1"])

        def status(self, *a, **k):
            return ("OK", [b"INBOX (UIDVALIDITY 7)"])

        def uid(self, cmd, *args):
            if cmd == "SEARCH":
                return ("OK", [b"10 11"])
            if cmd == "FETCH":
                return ("NO", [None])
            return ("NO", [])

    monkeypatch.setattr("mail_core.providers.imap.imaplib.IMAP4_SSL", FakeIMAP)
    p = ImapProvider(host="h", port=993, username="u", password="p")
    with pytest.raises(RuntimeError, match="UID FETCH"):
        p.fetch_metadata_page("INBOX", {"uid_next": 10, "uidvalidity": 7, "page_size": 50})


def test_imap_search_failure_raises_not_exhausted(monkeypatch):
    class FakeIMAP:
        def __init__(self, *a, **k):
            pass

        def login(self, *a):
            return ("OK", [b""])

        def logout(self):
            return ("OK", [b""])

        def select(self, *a, **k):
            return ("OK", [b"1"])

        def status(self, *a, **k):
            return ("OK", [b"INBOX (UIDVALIDITY 7)"])

        def uid(self, cmd, *args):
            if cmd == "SEARCH":
                return ("NO", [b""])
            return ("NO", [])

    monkeypatch.setattr("mail_core.providers.imap.imaplib.IMAP4_SSL", FakeIMAP)
    p = ImapProvider(host="h", port=993, username="u", password="p")
    with pytest.raises(RuntimeError, match="UID SEARCH"):
        p.fetch_metadata_page("INBOX", {"uid_next": 1, "uidvalidity": 7})


def test_complete_job_requires_owner():
    job = SimpleNamespace(
        id=uuid.uuid4(),
        status=JobStatus.CLAIMED.value,
        locked_by="w1",
        locked_at=datetime.now(timezone.utc),
    )
    with pytest.raises(JobOwnershipError):
        complete_job(_FakeSession(), job, worker_id="other")  # type: ignore[arg-type]
    complete_job(_FakeSession(), job, worker_id="w1")  # type: ignore[arg-type]
    assert job.status == JobStatus.DONE.value
    assert job.locked_by is None


def test_fail_job_requires_owner():
    job = SimpleNamespace(
        id=uuid.uuid4(),
        attempts=1,
        status=JobStatus.CLAIMED.value,
        last_error=None,
        locked_by="w1",
        locked_at=datetime.now(timezone.utc),
        run_after=datetime.now(timezone.utc),
    )
    with pytest.raises(JobOwnershipError):
        fail_job(_FakeSession(), job, "x", worker_id="nope", max_attempts=5)  # type: ignore[arg-type]


def test_soft_quota_pauses_archive(tmp_path, monkeypatch):
    from mail_core.blobs.quota import check_quota
    from mail_core.blobs import archive as archive_mod

    (tmp_path / "aa" / "bb").mkdir(parents=True)
    (tmp_path / "aa" / "bb" / "x.blob").write_bytes(b"12345")
    q = check_quota(tmp_path, soft_limit_bytes=3, hard_limit_bytes=1000)
    assert q.soft_exceeded and not q.hard_exceeded

    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))

    class _S:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def add(self, *a, **k):
            pass

        def commit(self):
            pass

        def get(self, *a, **k):
            return None

    with (
        patch("mail_core.db.session.get_session_factory", return_value=_S),
        patch.object(archive_mod, "BlobStore", return_value=SimpleNamespace(put=lambda d: None)),
    ):
        out = archive_mod.run_archive_batch(
            account_id=None,
            worker_id="w",
            payload={"soft_limit_bytes": 3, "hard_limit_bytes": 1000, "batch_size": 1},
        )
    assert out["status"] == "paused_quota"


def test_compose_imap_has_profile():
    text = Path("docker-compose.mail-core.yml").read_text()
    assert 'profiles: ["imap"]' in text
    assert "kkmail-mail-core-imap" in text


def test_scripts_prefer_python3_and_venv():
    chaos = Path("scripts/mail-core-chaos-lease.sh").read_text()
    assert ".venv/bin/python" in chaos
    start = Path("scripts/start-mail-core-imap.sh").read_text()
    assert "--profile imap" in start
    assert "command -v python3" in start
    side = Path("scripts/build-sidecar.sh").read_text()
    assert ".venv/bin/python" in side


def test_imap_decode_header_unknown_charset():
    from mail_core.providers.imap import _decode_header

    raw = "=?unknown-custom-charset?B?dGVzdA==?="
    decoded = _decode_header(raw)
    assert decoded == "test"


def test_imap_list_folders_case_insensitive_inbox(monkeypatch):
    class FakeIMAPList:
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "Inbox"', b'(\\HasNoChildren) "/" "Sent"']

        def logout(self):
            return "OK", []

    prov = ImapProvider("h", 993, "u", "p", use_ssl=False)
    monkeypatch.setattr(prov, "_connect", lambda: FakeIMAPList())
    folders = prov.list_folders()
    inbox = next(f for f in folders if f.name == "Inbox")
    assert inbox.role == "inbox"


def test_imap_fetch_metadata_page_bounded_search_pagination(monkeypatch):
    class FakeIMAPLarge:
        def select(self, *a, **k):
            return "OK", [b"1"]

        def status(self, *a, **k):
            return "OK", [b"INBOX (UIDVALIDITY 10)"]

        def uid(self, cmd, *args):
            if cmd == "SEARCH":
                # 1000 UIDs
                return "OK", [b" ".join(str(i).encode() for i in range(1, 1001))]
            if cmd == "FETCH":
                uid = args[0]
                return "OK", [
                    (
                        b"FLAGS (\\Seen)",
                        f"From: a@b.com\r\nSubject: Test {uid}\r\nDate: Wed, 21 Oct 2026 00:00:00 +0000\r\n\r\n".encode(),
                    )
                ]
            return "NO", []

        def logout(self):
            return "OK", []

    prov = ImapProvider("h", 993, "u", "p", use_ssl=False)
    monkeypatch.setattr(prov, "_connect", lambda: FakeIMAPLarge())
    page = prov.fetch_metadata_page("INBOX", {"uid_next": 1, "page_size": 2})
    assert len(page.items) == 2
    assert page.items[0].uid == 1
    assert page.items[1].uid == 2
    assert not page.exhausted
    assert page.next_cursor["uid_next"] == 3


def test_build_provider_imap_json_credentials_unpack():
    from mail_core.accounts.credentials import DictCredentialStore
    from mail_core.mail.storage.models import Account
    from mail_core.providers.factory import build_provider

    store = DictCredentialStore({
        "ref-dict": {"password": "real-secret-from-dict"},
        "ref-json": '{"password": "real-secret-from-json"}',
    })

    acc1 = Account(
        email="a@b.com",
        provider="imap",
        credential_ref="ref-dict",
        config={"imap_host": "mail.test", "port": 993},
    )
    p1 = build_provider(acc1, store)
    assert p1.password == "real-secret-from-dict"

    acc2 = Account(
        email="a@b.com",
        provider="imap",
        credential_ref="ref-json",
        config={"imap_host": "mail.test", "port": 993},
    )
    p2 = build_provider(acc2, store)
    assert p2.password == "real-secret-from-json"
