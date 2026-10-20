import os

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("LOGIN_PASSWORD", "admin123")

import web_outlook_app as appmod  # noqa: E402


REQUIRED_ROUTES = {
    "/api/accounts",
    "/api/groups",
    "/api/emails/<email_addr>",
    "/api/email/<email_addr>/<path:message_id>",
    "/api/emails/mark-read",
    "/api/emails/delete",
    "/api/outlook/send-mail",
    "/api/oauth/auth-url",
    "/api/projects",
    "/api/temp-emails",
    "/api/settings/test-webdav-backup",
}


def test_frontend_contract_routes_exist():
    rules = {rule.rule for rule in appmod.app.url_map.iter_rules()}
    missing = sorted(REQUIRED_ROUTES - rules)
    assert not missing, f"missing frontend contract routes: {missing}"
