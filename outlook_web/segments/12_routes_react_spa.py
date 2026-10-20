"""Serve the React SPA when frontend/dist exists. Old UI remains at /legacy."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from flask import Response, redirect, send_from_directory

if TYPE_CHECKING:
    from web_outlook_app import *  # noqa: F403


def _react_dist_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
        Path(app.root_path).parent / "frontend" / "dist",
        Path.cwd() / "frontend" / "dist",
    ]
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return candidates[0]


@app.route("/legacy")
@login_required
def legacy_index():
    """旧版模板界面，作为迁移期回退。"""
    return redirect("/") if not (Path(app.template_folder) / "index.html").is_file() else render_template(
        "index.html",
        app_version=APP_VERSION,
        changelog_url=CHANGELOG_URL,
        frontend_asset_hash=get_frontend_asset_hash(),
        skin_asset_hash=get_active_skin_asset_hash(),
        mail_fetch_timeout_seconds=get_mail_fetch_timeout_seconds(),
    )


def _spa_index_response() -> Response:
    dist = _react_dist_dir()
    index = dist / "index.html"
    if not index.is_file():
        # No built frontend yet — fall back to legacy template.
        return make_response(render_template(
            "index.html",
            app_version=APP_VERSION,
            changelog_url=CHANGELOG_URL,
            frontend_asset_hash=get_frontend_asset_hash(),
            skin_asset_hash=get_active_skin_asset_hash(),
            mail_fetch_timeout_seconds=get_mail_fetch_timeout_seconds(),
        ))
    response = make_response(send_from_directory(dist, "index.html"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


# Override the root index to prefer the React SPA when built.
# The original index() is still defined; we rebind the endpoint after it exists.
def _install_spa_index():
    view = login_required(_spa_index_response)
    view.__name__ = "index"
    app.view_functions["index"] = view


try:
    _install_spa_index()
except Exception as exc:  # pragma: no cover
    print(f"React SPA index install skipped: {exc}")


@app.route("/app")
@app.route("/app/<path:path>")
@login_required
def react_app_catchall(path=""):
    """SPA client routes. Static assets under /assets are served by Vite build."""
    dist = _react_dist_dir()
    if path:
        candidate = dist / path
        if candidate.is_file():
            return send_from_directory(dist, path)
    return _spa_index_response()


@app.route("/assets/<path:filename>")
def react_assets(filename):
    """Serve Vite build assets if present, otherwise fall through to legacy static."""
    dist = _react_dist_dir()
    asset = dist / "assets" / filename
    if asset.is_file():
        return send_from_directory(dist / "assets", filename)
    # Let Flask's normal static handler or existing /assets routes respond.
    return redirect(f"/static/{filename}")
