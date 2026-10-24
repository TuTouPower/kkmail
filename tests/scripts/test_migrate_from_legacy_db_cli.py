from __future__ import annotations

import pytest

from scripts import migrate_from_legacy_db


def test_legacy_migration_requires_explicit_source_and_target():
    with pytest.raises(SystemExit) as exc_info:
        migrate_from_legacy_db.parse_args([])

    assert exc_info.value.code == 2


def test_legacy_migration_prints_target_and_requires_confirmation(tmp_path, monkeypatch, capsys):
    source = tmp_path / "legacy.sqlite"
    source.touch()
    args = migrate_from_legacy_db.parse_args(
        [
            "--source",
            str(source),
            "--target-url",
            "postgresql://migrator:test-pw@127.0.0.1:5432/mailtarget",
        ]
    )
    monkeypatch.setattr(
        migrate_from_legacy_db,
        "migrate",
        lambda *_args: pytest.fail("migration ran without --yes"),
    )

    assert migrate_from_legacy_db.main(args) == 2
    captured = capsys.readouterr()
    assert f"Source SQLite: {source}" in captured.out
    assert "host=127.0.0.1 port=5432 database=mailtarget" in captured.out
    assert "test-pw" not in captured.out + captured.err
    assert "--yes" in captured.err


def test_legacy_migration_confirmation_passes_resolved_source_and_target(tmp_path, monkeypatch):
    source = tmp_path / "legacy.sqlite"
    source.touch()
    args = migrate_from_legacy_db.parse_args(
        [
            "--source",
            str(source),
            "--target-url",
            "postgresql://migrator:test-pw@127.0.0.1:5432/mailtarget",
            "--yes",
        ]
    )
    calls = []
    monkeypatch.setattr(
        migrate_from_legacy_db,
        "migrate",
        lambda source_path, target_url: calls.append((source_path, target_url)),
    )

    assert migrate_from_legacy_db.main(args) == 0
    assert calls == [
        (
            source.resolve(),
            "postgresql+psycopg://migrator:test-pw@127.0.0.1:5432/mailtarget",
        )
    ]
