import os

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("LOGIN_PASSWORD", "[REDACTED]")

import web_outlook_app as appmod  # noqa: E402


def test_login_then_spa_and_accounts():
    appmod.login_attempts.clear()
    with appmod.app.app_context():
        appmod.set_setting('login_password', appmod.hash_password('[REDACTED]'))
    client = appmod.app.test_client()
    login = client.post("/login", json={"password": "[REDACTED]"})
    assert login.status_code == 200
    assert login.get_json()["success"] is True

    home = client.get("/")
    assert home.status_code == 200
    assert b'id="root"' in home.data

    accounts = client.get("/api/accounts")
    assert accounts.status_code == 200
    payload = accounts.get_json()
    assert payload["success"] is True
    assert "accounts" in payload

    groups = client.get("/api/groups")
    assert groups.status_code == 200
    assert groups.get_json()["success"] is True
