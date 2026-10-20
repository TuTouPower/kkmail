from mail_core.providers import StubProvider


def test_stub_provider_surface():
    p = StubProvider()
    folders = p.list_folders()
    assert folders[0].role == "inbox"
    page = p.fetch_metadata_page("INBOX", None)
    assert page.exhausted
    assert p.fetch_mime("x").startswith(b"From:")
    assert p.apply_remote_operation("mark_read", {"remote_id": "1"}).success
    assert p.rate_limit_hint().max_requests_per_minute == 60
