"""A104: DB pool env vars must be parsed with validation and raise
DatabaseConfigError naming the variable and expected range."""
import pytest

from mail_core.db.session import DatabaseConfigError, _pool_kwargs


def test_defaults(monkeypatch):
    """t095: defaults derive from the single runtime budget (rewritten).

    The old assertion pinned pool_size/max_overflow to 10/10; t095 converges
    single-host defaults to 4/4 via ``runtime_budget``. The validation contract
    (env parsing + named errors) below is unchanged.
    """
    from mail_core import runtime_budget

    for var in (
        "MAIL_CORE_DB_POOL_SIZE",
        "MAIL_CORE_DB_MAX_OVERFLOW",
        "MAIL_CORE_DB_POOL_TIMEOUT",
        "MAIL_CORE_DB_POOL_RECYCLE",
    ):
        monkeypatch.delenv(var, raising=False)
    kw = _pool_kwargs()
    assert kw["pool_size"] == runtime_budget.DEFAULT_DB_POOL_SIZE
    assert kw["max_overflow"] == runtime_budget.DEFAULT_DB_MAX_OVERFLOW
    assert kw["pool_timeout"] == 30
    assert kw["pool_recycle"] == 1800


@pytest.mark.parametrize(
    "var,value",
    [
        ("MAIL_CORE_DB_POOL_SIZE", "abc"),
        ("MAIL_CORE_DB_POOL_SIZE", "0"),
        ("MAIL_CORE_DB_POOL_SIZE", "-1"),
        ("MAIL_CORE_DB_MAX_OVERFLOW", "abc"),
        ("MAIL_CORE_DB_MAX_OVERFLOW", "-1"),
        ("MAIL_CORE_DB_POOL_TIMEOUT", "abc"),
        ("MAIL_CORE_DB_POOL_TIMEOUT", "0"),
        ("MAIL_CORE_DB_POOL_TIMEOUT", "-5"),
        ("MAIL_CORE_DB_POOL_TIMEOUT", "nan"),
        ("MAIL_CORE_DB_POOL_TIMEOUT", "inf"),
        ("MAIL_CORE_DB_POOL_RECYCLE", "abc"),
        ("MAIL_CORE_DB_POOL_RECYCLE", "-1"),
    ],
)
def test_invalid_values_raise_named_error(monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    with pytest.raises(DatabaseConfigError, match=var):
        _pool_kwargs()


def test_valid_overrides(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_DB_POOL_SIZE", "5")
    monkeypatch.setenv("MAIL_CORE_DB_MAX_OVERFLOW", "0")
    monkeypatch.setenv("MAIL_CORE_DB_POOL_TIMEOUT", "12.5")
    monkeypatch.setenv("MAIL_CORE_DB_POOL_RECYCLE", "0")
    kw = _pool_kwargs()
    assert kw["pool_size"] == 5
    assert kw["max_overflow"] == 0
    assert kw["pool_timeout"] == 12.5
    assert kw["pool_recycle"] == 0
