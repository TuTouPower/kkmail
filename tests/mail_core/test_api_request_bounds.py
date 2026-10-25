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


def test_sidebar_layout_bounds_group_and_account_lists():
    import uuid

    from mail_core.api.accounts import SidebarLayoutIn

    account_id = str(uuid.UUID("00000000-0000-0000-0000-000000000001"))
    group_id = str(uuid.UUID("00000000-0000-0000-0000-000000000002"))
    base = {
        "group_ids": [],
        "master_account_ids": [],
        "ungrouped_account_ids": [],
        "group_account_ids": {},
        "expected_revision": "a" * 64,
    }

    with pytest.raises(ValidationError):
        SidebarLayoutIn(**{**base, "group_ids": [group_id] * 1001})
    with pytest.raises(ValidationError):
        SidebarLayoutIn(**{**base, "master_account_ids": [account_id] * 5001})
    with pytest.raises(ValidationError, match="group account lists"):
        SidebarLayoutIn(
            **{
                **base,
                "group_account_ids": {group_id: [account_id] * 5001},
            }
        )
