import pytest
from pydantic import ValidationError

from mail_core.api.auth_routes import LoginIn, PasswordChangeIn


def test_login_password_schema_accepts_maximum_length():
    assert len(LoginIn(password="p" * 1024).password) == 1024


def test_password_change_schema_accepts_maximum_length():
    body = PasswordChangeIn(current_login_password="c" * 1024, login_password="n" * 1024)

    assert len(body.current_login_password) == 1024
    assert len(body.login_password) == 1024


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (LoginIn, {"password": "p" * 1025}),
        (PasswordChangeIn, {"current_login_password": "c" * 1025, "login_password": "new-password"}),
        (PasswordChangeIn, {"current_login_password": "current-password", "login_password": "n" * 1025}),
    ],
)
def test_auth_password_schemas_reject_overlong_values(model, values):
    with pytest.raises(ValidationError):
        model(**values)
