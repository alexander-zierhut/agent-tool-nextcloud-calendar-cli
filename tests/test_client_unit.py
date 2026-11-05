"""Transport corners: retry policy and status mapping. Hermetic.

MockTransport stands in for the network only to pin what THIS client does with
a status code or a connection failure; it does not simulate CalDAV semantics
(those are tested against a real Nextcloud in the integration tier).
"""

from __future__ import annotations

import httpx
import pytest

from nextcloudcalendar import client as C
from nextcloudcalendar.errors import ApiError, AuthError, ConflictError, NotFoundError, ValidationError

SABRE_412 = """<?xml version="1.0"?><d:error xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns">
<s:exception>Sabre\\DAV\\Exception\\PreconditionFailed</s:exception>
<s:message>An If-Match header was specified, but none of the specified ETags matched.</s:message></d:error>"""


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(C.time, "sleep", lambda s: slept.append(s))
    return slept


def _client(handler):
    c = C.Client("https://cloud.example.test", "alex", "pw")
    c._client = httpx.Client(transport=httpx.MockTransport(handler), auth=("alex", "pw"))
    return c


def _seq(*responses):
    calls = []

    def handler(req):
        calls.append(req.method)
        r = responses[min(len(calls), len(responses)) - 1]
        if isinstance(r, Exception):
            raise r
        return r

    return handler, calls


def test_read_retries_5xx_then_succeeds():
    h, calls = _seq(httpx.Response(503), httpx.Response(207, text="<x/>"))
    assert _client(h).request("PROPFIND", "/remote.php/dav/").status_code == 207
    assert calls == ["PROPFIND", "PROPFIND"]


def test_write_does_not_retry_5xx():
    h, calls = _seq(httpx.Response(503), httpx.Response(201))
    with pytest.raises(ApiError):
        _client(h).request("PUT", "/remote.php/dav/x.ics", content="x")
    assert calls == ["PUT"]


def test_write_retries_429_because_it_was_not_processed():
    h, calls = _seq(httpx.Response(429), httpx.Response(201))
    assert _client(h).request("PUT", "/remote.php/dav/x.ics", content="x").status_code == 201
    assert calls == ["PUT", "PUT"]


def test_write_retries_a_connect_error_but_not_a_read_timeout():
    h, calls = _seq(httpx.ConnectError("refused"), httpx.Response(201))
    assert _client(h).request("PUT", "/remote.php/dav/x.ics", content="x").status_code == 201
    h2, calls2 = _seq(httpx.ReadTimeout("slow"), httpx.Response(201))
    with pytest.raises(ApiError):
        _client(h2).request("PUT", "/remote.php/dav/x.ics", content="x")
    assert calls2 == ["PUT"]


def test_retry_after_is_a_floor_not_a_shortcut(_no_sleep):
    h, _ = _seq(httpx.Response(503, headers={"Retry-After": "0"}), httpx.Response(207, text="<x/>"))
    _client(h).request("PROPFIND", "/remote.php/dav/")
    assert _no_sleep[0] >= 1.0  # the backoff for attempt 1, not Retry-After's 0


def test_backoff_is_capped():
    assert C._backoff(10, "3600") <= 30.5


def test_gives_up_after_max_attempts():
    h, calls = _seq(httpx.Response(503))
    with pytest.raises(ApiError):
        _client(h).request("GET", "/remote.php/dav/x.ics")
    assert len(calls) == C._MAX_ATTEMPTS


@pytest.mark.parametrize("status, exc, code", [
    (401, AuthError, 4), (403, AuthError, 4), (404, NotFoundError, 5),
    (409, ConflictError, 6), (412, ConflictError, 6), (400, ValidationError, 7), (415, ValidationError, 7),
])
def test_status_mapping(status, exc, code):
    h, _ = _seq(httpx.Response(status, text=SABRE_412 if status == 412 else ""))
    with pytest.raises(exc) as ei:
        _client(h).request("PUT", "/remote.php/dav/x.ics", content="x")
    assert ei.value.exit_code == code


def test_412_message_says_nothing_was_written():
    h, _ = _seq(httpx.Response(412, text=SABRE_412))
    with pytest.raises(ConflictError) as ei:
        _client(h).request("PUT", "/remote.php/dav/x.ics", content="x")
    assert "Nothing was written" in ei.value.message


def test_redirect_means_wrong_base_url():
    h, _ = _seq(httpx.Response(301, headers={"location": "https://cloud.example.test/login"}))
    with pytest.raises(ApiError) as ei:
        _client(h).request("GET", "/remote.php/dav/x.ics")
    assert "base URL" in ei.value.message


def test_dry_run_never_touches_the_network():
    def boom(req):
        raise AssertionError("network used under --dry-run")

    c = _client(boom)
    c.dry_run = True
    with pytest.raises(C.DryRun):
        c.request("PUT", "/remote.php/dav/x.ics", content="x")
    # reads still run under --dry-run
    h, _ = _seq(httpx.Response(207, text="<x/>"))
    c2 = _client(h)
    c2.dry_run = True
    assert c2.request("PROPFIND", "/remote.php/dav/").status_code == 207
