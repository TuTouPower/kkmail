import web_outlook_app as appmod


def _login(client):
    appmod.login_attempts.clear()
    with appmod.app.app_context():
        appmod.set_setting('login_password', appmod.hash_password('[REDACTED]'))
    login = client.post("/login", json={"password": "[REDACTED]"})
    assert login.status_code == 200
    assert login.get_json()["success"] is True


def test_login_then_spa_and_accounts(fake_frontend_dist):
    client = appmod.app.test_client()
    _login(client)

    home = client.get("/")
    assert home.status_code == 200
    assert b'id="root"' in home.data
    assert 'no-store' in home.headers.get('Cache-Control', '')

    asset = client.get("/assets/app-test.js")
    assert asset.status_code == 200
    assert b"console.log" in asset.data

    accounts = client.get("/api/accounts")
    assert accounts.status_code == 200
    payload = accounts.get_json()
    assert payload["success"] is True
    assert "accounts" in payload

    groups = client.get("/api/groups")
    assert groups.status_code == 200
    assert groups.get_json()["success"] is True


def test_root_falls_back_to_legacy_without_dist(tmp_path, monkeypatch):
    monkeypatch.setenv("KKMAIL_FRONTEND_DIST", str(tmp_path / "missing"))
    monkeypatch.setattr(appmod, "_react_dist_dir", lambda: tmp_path / "missing")
    client = appmod.app.test_client()
    _login(client)
    home = client.get("/")
    assert home.status_code == 200
    assert b'id="root"' not in home.data


def test_unauthenticated_root_redirects_to_login(fake_frontend_dist):
    client = appmod.app.test_client()
    response = client.get("/")
    assert response.status_code in (301, 302)
    assert "/login" in response.headers["Location"]


def test_frontend_dist_env_override(fake_frontend_dist):
    assert appmod._react_dist_dir() == fake_frontend_dist


def test_favicon_served_from_dist(fake_frontend_dist):
    (fake_frontend_dist / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    client = appmod.app.test_client()
    res = client.get("/favicon.svg")
    assert res.status_code == 200
    assert res.mimetype == "image/svg+xml"


def test_dist_dir_resolution_survives_shallow_entry_path(monkeypatch, tmp_path):
    """In Docker the app lives at /app/web_outlook_app.py; parents[2] does not exist there."""
    monkeypatch.delenv("KKMAIL_FRONTEND_DIST", raising=False)
    monkeypatch.setitem(appmod._react_dist_dir.__globals__, "__file__", "/web_outlook_app.py")
    result = appmod._react_dist_dir()
    assert result.name == "dist"
