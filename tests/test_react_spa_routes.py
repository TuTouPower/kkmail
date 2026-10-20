import os

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("LOGIN_PASSWORD", "admin123")

import web_outlook_app as appmod  # noqa: E402


def test_react_spa_routes_registered():
    rules = {rule.rule for rule in appmod.app.url_map.iter_rules()}
    assert "/" in rules
    assert "/legacy" in rules
    assert "/app" in rules
    view = appmod.app.view_functions["index"]
    assert getattr(view, "__wrapped__", view).__name__ in {"_spa_index_response", "index"}
