import os

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("LOGIN_PASSWORD", "admin123")

import web_outlook_app as appmod  # noqa: E402


def test_authenticated_management_endpoints():
    appmod.login_attempts.clear()
    with appmod.app.app_context():
        appmod.set_setting('login_password', appmod.hash_password('admin123'))
    client = appmod.app.test_client()
    login = client.post("/login", json={"password": "admin123"})
    assert login.get_json()["success"] is True

    for path in (
        "/api/tags",
        "/api/projects",
        "/api/temp-emails",
        "/api/accounts/forwarding-logs",
        "/api/oauth/auth-url",
        "/legacy",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
