"""A285: ``_may_accept_keyword`` policy for uninspectable signatures.

The old code returned True when ``inspect.signature`` failed while its
comment claimed an unknown signature is not proof that omitting the
session is safe -- comment and behaviour contradicted each other, and
the True path made ``CompositeCredentialStore`` pass ``session=`` into
a callable that might not accept it, surfacing a raw TypeError.

Pinned policy: an unknown signature means the session is NOT passed
(the store keeps working without the transactional session) and the
fallback is logged, so the downgrade is never silent.
"""

from __future__ import annotations

import logging

import pytest

from mail_core.accounts.credentials import CompositeCredentialStore, _may_accept_keyword


class _UninspectableCallable:
    """A callable whose signature cannot be inspected and which does
    not accept a ``session`` keyword."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    @property
    def __signature__(self):  # noqa: ANN202 - deliberately broken
        raise ValueError("signature unavailable")

    def __call__(self, credential_ref, secret):
        self.calls.append((credential_ref, secret))


class _UninspectableStore:
    def __init__(self) -> None:
        self.put_secret = _UninspectableCallable()
        self.delete_calls: list[str] = []

    def get_secret(self, credential_ref):
        raise KeyError(credential_ref)

    def delete_secret(self, credential_ref):
        self.delete_calls.append(credential_ref)


def test_may_accept_keyword_returns_false_for_uninspectable_signature(caplog):
    callable_obj = _UninspectableCallable()
    with caplog.at_level(logging.WARNING, logger="mail_core.accounts.credentials"):
        assert _may_accept_keyword(callable_obj, "session") is False
    assert any("signature" in record.message for record in caplog.records)


def test_composite_omits_session_for_uninspectable_store():
    target = _UninspectableStore()
    store = CompositeCredentialStore(db=target)

    # Must not raise TypeError from passing an unsupported keyword.
    store.put_secret("account:one", "secret", session=object())
    store.delete_secret("account:one", session=object())

    assert target.put_secret.calls == [("account:one", "secret")]
    assert target.delete_calls == ["account:one"]


def test_may_accept_keyword_still_detects_real_signatures():
    def accepts(ref, secret, *, session=None):
        pass

    def rejects(ref, secret):
        pass

    def var_keyword(ref, secret, **kwargs):
        pass

    assert _may_accept_keyword(accepts, "session") is True
    assert _may_accept_keyword(rejects, "session") is False
    assert _may_accept_keyword(var_keyword, "session") is True

