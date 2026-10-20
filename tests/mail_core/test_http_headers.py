from mail_core.api.http_headers import content_disposition_attachment


def test_content_disposition_strips_crlf_and_quotes():
    h = content_disposition_attachment('report\r\nSet-Cookie: x="y".pdf')
    assert "\r" not in h and "\n" not in h
    assert 'filename="' in h
    assert "filename*=UTF-8''" in h
