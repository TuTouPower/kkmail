import web_outlook_app as appmod


def test_authenticated_management_endpoints():
    appmod.login_attempts.clear()
    with appmod.app.app_context():
        appmod.set_setting('login_password', appmod.hash_password('[REDACTED]'))
    client = appmod.app.test_client()
    login = client.post("/login", json={"password": "[REDACTED]"})
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
