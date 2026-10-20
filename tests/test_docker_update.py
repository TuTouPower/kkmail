"""Docker in-app update removed — keep a marker so old CI names do not collect failures."""

import pytest

pytestmark = pytest.mark.skip(reason="DOCKER_UPDATE routes removed with 09_routes_system_update.py")


def test_docker_update_removed():
    assert True
