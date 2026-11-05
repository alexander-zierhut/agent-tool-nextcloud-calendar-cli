"""The integration tier's write-safety interlock is armed.

The integration tests create, move and delete events and assert who got mailed.
That must never reach a real calendar, so `conftest._assert_loopback` refuses
any server that is not on loopback. This meta-test lives in a collected file on
purpose: pytest does not collect `test_*` functions from conftest.py.
"""

from __future__ import annotations

import pytest

from conftest import NC_URL, _assert_loopback


@pytest.mark.parametrize("url", [
    "https://nextcloud.example.com",
    "https://cloud.example.test:8443/nextcloud",
    "http://10.0.0.5:8089",
    "http://192.168.1.10",
])
def test_interlock_refuses_non_loopback(url):
    with pytest.raises(RuntimeError, match="not loopback"):
        _assert_loopback(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8089", "http://localhost:8089", "http://[::1]:8089"])
def test_interlock_allows_loopback(url):
    _assert_loopback(url)


def test_the_configured_test_server_passes_the_interlock():
    """Whatever NEXTCLOUDCALENDAR_TEST_URL says, the stack fixture would refuse a
    non-loopback one; this pins that the default is loopback."""
    _assert_loopback(NC_URL)
