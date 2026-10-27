"""A171: is_restricted_ip must cover CGNAT / multicast / site-local ranges.

Previously the check OR-ed is_private/is_loopback/is_link_local/is_reserved/
is_unspecified, which misses 100.64.0.0/10 (CGNAT, is_private is False for
it in CPython), 224.0.0.0/4 (multicast) and fec0::/10 (IPv6 site-local).
The fix uses ``not ip.is_global`` as the restricted criterion.
"""

from __future__ import annotations

import pytest

from mail_core.providers.host_security import is_restricted_ip


@pytest.mark.parametrize(
    "address",
    [
        "100.64.0.1",  # CGNAT shared address space
        "100.127.255.254",  # CGNAT upper edge
        "224.0.0.1",  # multicast
        "239.255.255.255",  # multicast upper edge
        "fec0::1",  # IPv6 site-local (deprecated but routable on some nets)
        "10.0.0.5",  # RFC1918 (already covered, regression guard)
        "192.168.1.1",  # RFC1918
        "172.16.0.1",  # RFC1918
        "127.0.0.1",  # loopback
        "169.254.1.1",  # link-local
        "0.0.0.0",  # unspecified
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
    ],
)
def test_restricted_addresses(address):
    assert is_restricted_ip(address) is True


@pytest.mark.parametrize(
    "address",
    [
        "8.8.8.8",
        "1.1.1.1",
        "2001:4860:4860::8888",
    ],
)
def test_global_addresses_not_restricted(address):
    assert is_restricted_ip(address) is False
