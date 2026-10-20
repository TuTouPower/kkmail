import tempfile
from pathlib import Path

import web_outlook_app as appmod


def test_tests_never_use_repo_database():
    """conftest.py points DATABASE_PATH at a temp dir before the app is imported."""
    repo_root = Path(appmod.__file__).resolve().parent
    db = Path(appmod.DATABASE).resolve()
    assert db != (repo_root / "data" / "outlook_accounts.db").resolve()
    assert repo_root not in db.parents
    assert Path(tempfile.gettempdir()).resolve() in db.parents
