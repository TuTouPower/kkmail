from __future__ import annotations

import pytest

from scripts import migrate_from_legacy_db


def test_legacy_migration_requires_explicit_source_and_target():
    with pytest.raises(SystemExit) as exc_info:
        migrate_from_legacy_db.parse_args([])

    assert exc_info.value.code == 2


# REPLACED (A132): this test previously passed the password-bearing target
# URL via --target-url. A132 forbids passwords on the command line (process
# list / shell history leak), so the same scenario now supplies the URL
# through --target-url-env. Assertions are unchanged.
def test_legacy_migration_prints_target_and_requires_confirmation(tmp_path, monkeypatch, capsys):
    source = tmp_path / "legacy.sqlite"
    source.touch()
    monkeypatch.setenv(
        "LEGACY_MIGRATION_TARGET_URL",
        "postgresql://migrator:test-pw@127.0.0.1:5432/mailtarget",
    )
    args = migrate_from_legacy_db.parse_args(
        [
            "--source",
            str(source),
            "--target-url-env",
            "LEGACY_MIGRATION_TARGET_URL",
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


# REPLACED (A132): see note above. The confirmed-run scenario now supplies
# the password-bearing URL through the MAIL_CORE_DATABASE_URL fallback
# instead of --target-url; the resolved call assertion is unchanged.
def test_legacy_migration_confirmation_passes_resolved_source_and_target(tmp_path, monkeypatch):
    source = tmp_path / "legacy.sqlite"
    source.touch()
    monkeypatch.setenv(
        "MAIL_CORE_DATABASE_URL",
        "postgresql://migrator:test-pw@127.0.0.1:5432/mailtarget",
    )
    args = migrate_from_legacy_db.parse_args(
        [
            "--source",
            str(source),
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


def test_legacy_migration_rejects_password_in_target_url_cli_arg(tmp_path, monkeypatch, capsys):
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
    monkeypatch.setattr(
        migrate_from_legacy_db,
        "migrate",
        lambda *_args: pytest.fail("migration ran with a password on the command line"),
    )

    assert migrate_from_legacy_db.main(args) == 2
    captured = capsys.readouterr()
    assert "--target-url-env" in captured.err
    assert "test-pw" not in captured.out + captured.err


def test_legacy_migration_passwordless_target_url_cli_arg_still_works(tmp_path, monkeypatch):
    source = tmp_path / "legacy.sqlite"
    source.touch()
    args = migrate_from_legacy_db.parse_args(
        [
            "--source",
            str(source),
            "--target-url",
            "postgresql://migrator@127.0.0.1:5432/mailtarget",
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
    assert calls == [(source.resolve(), "postgresql+psycopg://migrator@127.0.0.1:5432/mailtarget")]


def test_legacy_migration_target_url_env_missing_variable_fails(tmp_path, monkeypatch, capsys):
    source = tmp_path / "legacy.sqlite"
    source.touch()
    monkeypatch.delenv("LEGACY_MIGRATION_UNSET_URL", raising=False)
    args = migrate_from_legacy_db.parse_args(
        [
            "--source",
            str(source),
            "--target-url-env",
            "LEGACY_MIGRATION_UNSET_URL",
            "--yes",
        ]
    )
    monkeypatch.setattr(
        migrate_from_legacy_db,
        "migrate",
        lambda *_args: pytest.fail("migration ran without a target URL"),
    )

    assert migrate_from_legacy_db.main(args) == 2
    assert "LEGACY_MIGRATION_UNSET_URL" in capsys.readouterr().err


def test_legacy_migration_without_any_target_source_fails(tmp_path, monkeypatch, capsys):
    source = tmp_path / "legacy.sqlite"
    source.touch()
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    args = migrate_from_legacy_db.parse_args(["--source", str(source), "--yes"])
    monkeypatch.setattr(
        migrate_from_legacy_db,
        "migrate",
        lambda *_args: pytest.fail("migration ran without a target URL"),
    )

    assert migrate_from_legacy_db.main(args) == 2
    assert "MAIL_CORE_DATABASE_URL" in capsys.readouterr().err
