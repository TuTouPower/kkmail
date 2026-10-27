"""documents.py front matter 序列化/解析与原子写专项守卫。"""
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

import repo_task.context as ctx
from repo_task.documents import (
    _quote,
    _unquote,
    dump_front_matter,
    parse_front_matter_text,
)


def test_quote_escapes_newline_and_carriage_return():
    assert _quote("a\nb") == '"a\\nb"'
    assert _quote("a\rb") == '"a\\rb"'


def test_quote_unquote_roundtrip_with_newlines():
    for value in ("plain", "a\nb", "a\rb", 'quote " and \\ slash', "trail\\"):
        assert _unquote(_quote(value)) == value


def test_unquote_decodes_escape_sequences_not_literal_chars():
    # _unquote 须按转义语义解码：\\n -> 换行、\\\\ -> 单个反斜杠，
    # 不能把任意转义一律剥成后一个字符（否则字面 \n 与真换行不可区分）。
    assert _unquote(r'"a\nb"') == "a\nb"
    assert _unquote(r'"a\\nb"') == "a\\nb"
    assert _unquote(r'"a\"b"') == 'a"b'


def test_dumped_front_matter_with_newline_title_stays_single_line_and_parses_back():
    fm = {"tid": "t001", "title": "bad\nnote: injected", "note": "x\ry"}
    text = dump_front_matter(fm)
    parsed, _ = parse_front_matter_text(text + "\nbody", source="test")
    assert parsed["title"] == "bad\nnote: injected"
    assert parsed["note"] == "x\ry"
    assert "injected" not in parsed


def test_single_quoted_value_restores_doubled_quote_escape():
    fm, _ = parse_front_matter_text(
        "---\ntitle: 'it''s fine'\n---\nbody", source="test"
    )
    assert fm["title"] == "it's fine"
    assert _unquote("'a''b'") == "a'b"


def test_duplicate_front_matter_key_is_an_error():
    with pytest.raises(ctx.TaskDataError, match="重复键"):
        parse_front_matter_text(
            "---\ntitle: one\ntitle: two\n---\nbody", source="test"
        )


def test_unquoted_bracket_value_keeps_hash_content():
    fm, _ = parse_front_matter_text(
        "---\nnote: [a] # not a comment tail\n---\nbody", source="test"
    )
    assert fm["note"] == "[a] # not a comment tail"


def test_unquoted_plain_value_still_strips_spaced_comment():
    fm, _ = parse_front_matter_text(
        "---\nnote: plain value # trailing comment\n---\nbody", source="test"
    )
    assert fm["note"] == "plain value"


def test_add_edit_entry_rejects_newlines_in_title_and_note():
    from repo_task import lifecycle

    assert lifecycle._reject_newlines("title", "a\nb") is not None
    assert lifecycle._reject_newlines("note", "a\rb") is not None
    assert lifecycle._reject_newlines("title", "normal title") is None
