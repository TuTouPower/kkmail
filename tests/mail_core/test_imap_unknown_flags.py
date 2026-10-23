from unittest.mock import Mock

import pytest

from mail_core.providers.imap import ImapProvider, _parse_message_meta_from_fetch


@pytest.mark.parametrize('flags,expected', [
    (b'', (None, None)),
    (b' FLAGS ()', (False, False)),
    (br' FLAGS (\Seen \Flagged)', (True, True)),
    (br' FLAGS (\SeenLater \FlaggedElse)', (False, False)),
    (br' FLAGS (\sEeN \fLaGgEd)', (True, True)),
])
def test_imap_metadata_distinguishes_missing_flags_from_explicit_empty(flags, expected):
    meta = _parse_message_meta_from_fetch(
        (b'1 (UID 1' + flags + b')', b'Subject: mail\r\n\r\n'), 1, 'INBOX', 1,
    )
    assert (meta.is_read, meta.is_flagged) == expected


@pytest.mark.parametrize('response,expected', [
    (b'1 (UID 1)', []),
    (b'1 (UID 1 FLAGS ())', [{'is_read': False, 'is_flagged': False}]),
    (br'1 (UID 1 FLAGS (\SeenLater \FlaggedElse))', [{'is_read': False, 'is_flagged': False}]),
    (br'1 (UID 1 FLAGS (\sEeN \fLaGgEd))', [{'is_read': True, 'is_flagged': True}]),
])
def test_imap_delta_does_not_invent_flags_when_fetch_omits_them(response, expected):
    client = Mock()
    client.uid.return_value = ('OK', [response])
    provider = ImapProvider(host='unused', port=143, username='test', password='')
    changes = provider._fetch_flags_for_uids(client, 'INBOX', 1, [1])
    assert [change.flags for change in changes] == expected
