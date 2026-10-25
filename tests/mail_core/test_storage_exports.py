from mail_core.mail import storage
from mail_core.mail.storage import models


def test_storage_package_exports_every_orm_model():
    model_names = {
        name
        for name, value in vars(models).items()
        if isinstance(value, type) and value.__module__ == models.__name__
    }

    assert set(storage.__all__) == model_names
    assert len(storage.__all__) == len(model_names)
    assert all(getattr(storage, name) is getattr(models, name) for name in model_names)
