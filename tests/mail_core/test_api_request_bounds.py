import pytest
from pydantic import ValidationError

from mail_core.api.accounts import SettingsUpdateIn


def test_settings_patch_accepts_limit_boundaries():
    model = SettingsUpdateIn(settings={"k" * 128: "v" * 4096})
    assert len(model.settings) == 1


def test_settings_patch_rejects_excessive_key_count():
    settings = {f"key-{index}": "value" for index in range(101)}
    with pytest.raises(ValidationError):
        SettingsUpdateIn(settings=settings)


def test_settings_patch_rejects_oversized_key_or_value():
    with pytest.raises(ValidationError, match="setting keys"):
        SettingsUpdateIn(settings={"k" * 129: "value"})
    with pytest.raises(ValidationError, match="setting values"):
        SettingsUpdateIn(settings={"key": "v" * 4097})
