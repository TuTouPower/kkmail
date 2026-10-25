from importlib import import_module
from inspect import isfunction

import mail_core.mail.application as application


def test_public_application_functions_are_package_exports():
    modules = (
        "accounts",
        "attachments",
        "message_details",
        "mutations",
        "queries",
        "remote_ops",
        "search",
    )
    for module_name in modules:
        module = import_module(f"{application.__name__}.{module_name}")
        for name, value in vars(module).items():
            if not isfunction(value) or value.__module__ != module.__name__ or name.startswith("_"):
                continue
            assert name in application.__all__, (
                f"{module_name}.{name} is missing from application.__all__"
            )
            assert getattr(application, name) is value, (
                f"{module_name}.{name} does not resolve through application"
            )
