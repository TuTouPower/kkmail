"""Serve the React SPA when frontend/dist exists. Old UI remains at /legacy."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from flask import Response, abort, redirect, send_from_directory

if TYPE_CHECKING:
    from web_outlook_app import *  # noqa: F403


def _react_dist_dir() -> Path:
    candidates = []
    override = os.getenv("KKMAIL_FRONTEND_DIST", "").strip()
    if override:
        candidates.append(Path(override))
    candidates.append(resource_path("frontend", "dist"))
    # Segments are exec'd into web_outlook_app, so __file__ may be the entry
    # module at a shallow path such as /app/web_outlook_app.py (Docker).
    # Walk up a few parents instead of indexing parents[2], which raised
    # IndexError there and turned every page into a 500.
    here = Path(__file__).resolve()
    candidates += [parent / "frontend" / "dist" for parent in list(here.parents)[:3]]
    candidates += [
        Path(app.root_path) / "frontend" / "dist",
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
    if not (Path(app.template_folder) / "index.html").is_file():
        return redirect("/")
    return index()


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
    html = index.read_text(encoding="utf-8")
    # Cutover hook: when MAIL_CORE_DEFAULT=1, tell the SPA to prefer mail-core
    # list/reader. Login and other Flask routes are unchanged.
    if os.environ.get("MAIL_CORE_DEFAULT", "").strip().lower() in {"1", "true", "yes", "on"}:
        import json

        base = os.environ.get("MAIL_CORE_PUBLIC_BASE", "/mail-core").strip() or "/mail-core"
        cfg = {"mailCoreDefault": True, "mailCoreBase": base}
        snippet = (
            "<script>window.__KKMAIL_CONFIG__="
            + json.dumps(cfg)
            + ";</script>"
        )
        if "</head>" in html:
            html = html.replace("</head>", snippet + "</head>", 1)
        else:
            html = snippet + html
        response = make_response(html)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
    else:
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
    # Explicit legacy routes (/assets/index.css, /assets/active-skin.css) match first;
    # anything else missing is a real 404, not a redirect into /static.
    abort(404)


@app.route("/favicon.svg")
def react_favicon():
    """index.html references /favicon.svg; serve it from the Vite dist (public/)."""
    dist = _react_dist_dir()
    icon = dist / "favicon.svg"
    if icon.is_file():
        response = make_response(send_from_directory(dist, "favicon.svg", mimetype="image/svg+xml"))
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response
    abort(404)
