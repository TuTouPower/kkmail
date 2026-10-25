from __future__ import annotations

import importlib
from pathlib import Path

import pytest

app_module = importlib.import_module("mail_core.api.app")


@pytest.mark.parametrize("path", ["api/mail", "health", "ready/check", "docs/openapi", "openapi.json", "assets/app.js"])
def test_spa_fallback_reserves_exact_root_segments(path):
    assert app_module._is_reserved_spa_path(path)


@pytest.mark.parametrize("path", ["apiary/mail", "healthcare", "ready-made", "docs2", "assets-old/app.js"])
def test_spa_fallback_does_not_reserve_prefix_collisions(path):
    assert not app_module._is_reserved_spa_path(path)


def test_spa_candidate_requires_resolved_file_inside_dist(tmp_path):
    asset = tmp_path / "app.js"
    asset.write_text("ok")

    assert app_module._resolve_spa_candidate(tmp_path.resolve(), "app.js") == asset.resolve()
    assert app_module._resolve_spa_candidate(tmp_path.resolve(), "../outside.js") is None


def test_spa_candidate_logs_resolve_errors_at_debug(monkeypatch, tmp_path, caplog):
    candidate = tmp_path / "loop"
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == candidate:
            raise RuntimeError("symlink loop")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with caplog.at_level("DEBUG", logger="mail_core.api"):
        result = app_module._resolve_spa_candidate(tmp_path, "loop")

    assert result is None
    assert "SPA fallback path resolution failed (RuntimeError)" in caplog.text
    assert "symlink loop" not in caplog.text
