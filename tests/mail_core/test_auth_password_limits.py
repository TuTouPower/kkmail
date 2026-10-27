"""Password schema limits follow the shared bcrypt byte contract (A119).

Replaces the previous 1024-character schema tests wholesale: the schema
limit is now defined by mail_core.security.auth.MAX_PASSWORD_BYTES
(72 UTF-8 bytes, the bcrypt input limit), not an unrelated character count.
A password is acceptable only when its UTF-8 encoding fits that budget —
character length alone is not the contract (e.g. 36 'é' = 72 bytes passes,
37 'é' = 74 bytes fails).
"""

import pytest
from pydantic import ValidationError

from mail_core.api.auth_routes import LoginIn, PasswordChangeIn
from mail_core.security.auth import MAX_PASSWORD_BYTES


def test_login_password_schema_accepts_maximum_byte_length():
    assert len(LoginIn(password="p" * MAX_PASSWORD_BYTES).password) == MAX_PASSWORD_BYTES
    assert LoginIn(password="é" * 36).password == "é" * 36  # 72 UTF-8 bytes


def test_password_change_schema_accepts_maximum_byte_length():
    body = PasswordChangeIn(
        current_login_password="c" * MAX_PASSWORD_BYTES,
        login_password="é" * 36,
    )

    assert len(body.current_login_password.encode("utf-8")) == MAX_PASSWORD_BYTES
    assert len(body.login_password.encode("utf-8")) == MAX_PASSWORD_BYTES


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (LoginIn, {"password": "p" * (MAX_PASSWORD_BYTES + 1)}),
        (LoginIn, {"password": "é" * 37}),  # 74 UTF-8 bytes
        (PasswordChangeIn, {"current_login_password": "c" * (MAX_PASSWORD_BYTES + 1), "login_password": "new-password"}),
        (PasswordChangeIn, {"current_login_password": "current-password", "login_password": "n" * (MAX_PASSWORD_BYTES + 1)}),
        (PasswordChangeIn, {"current_login_password": "current-password", "login_password": "é" * 37}),
    ],
)
def test_auth_password_schemas_reject_overlong_values(model, values):
    with pytest.raises(ValidationError):
        model(**values)
