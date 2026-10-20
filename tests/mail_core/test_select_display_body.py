"""Unit tests for display-body selection (no database)."""

from mail_core.mail.application.queries import select_display_body


def test_select_display_body_prefers_html():
    body, kind = select_display_body("<p>x</p>", "x")
    assert kind == "html"
    assert body == "<p>x</p>"


def test_select_display_body_plain():
    body, kind = select_display_body(None, "plain")
    assert kind == "text"
    assert body == "plain"


def test_select_display_body_empty():
    body, kind = select_display_body(None, None)
    assert kind == "empty"
    assert body == ""


def test_select_display_body_empty_strings():
    body, kind = select_display_body("", "")
    assert kind == "empty"
    assert body == ""
