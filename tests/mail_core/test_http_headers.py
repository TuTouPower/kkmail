from mail_core.api.http_headers import content_disposition_attachment


def test_content_disposition_strips_crlf_and_quotes():
    h = content_disposition_attachment('report\r\nSet-Cookie: x="y".pdf')
    assert "\r" not in h and "\n" not in h
    assert "%0D" not in h.upper() and "%0A" not in h.upper()
    assert 'filename="' in h
    assert "filename*=UTF-8''" in h
    # Colon stripped from ASCII fallback; no injectable header line shape.
    assert "Set-Cookie:" not in h


def test_content_disposition_strips_path_components():
    h = content_disposition_attachment("../../etc/passwd.pdf")
    assert "../" not in h
    assert "passwd.pdf" in h


def test_content_disposition_unicode_filename_star():
    h = content_disposition_attachment("账单.pdf")
    assert "filename*=UTF-8''" in h
    assert "\r" not in h and "\n" not in h
    # Must be encodable as latin-1 for HTTP response headers
    h.encode("latin-1")
    assert 'filename="__' in h
