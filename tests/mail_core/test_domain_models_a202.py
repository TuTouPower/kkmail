"""A202: mail/domain/models.py value objects had no production or test
references anywhere (only the domain package __init__ re-exported them).
The module and its re-exports are deleted; enums/archive stay.
"""

from __future__ import annotations

import importlib

import pytest


def test_domain_models_module_deleted():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mail_core.mail.domain.models")


def test_domain_package_no_longer_exports_value_objects():
    domain = importlib.import_module("mail_core.mail.domain")

    for name in ("AccountRef", "FolderRef", "MessageMetadata", "SyncCheckpointView"):
        assert not hasattr(domain, name), name
        assert name not in domain.__all__


def test_domain_enums_and_archive_still_available():
    domain = importlib.import_module("mail_core.mail.domain")

    assert domain.ArchiveState is not None
    assert domain.can_transition is not None
