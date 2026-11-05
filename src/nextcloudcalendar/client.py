"""CalDAV transport for Nextcloud.

Not shared with the other agent-tool CLIs — the family shares the *contract*, not
the transport, and every rule here is CalDAV/Nextcloud-shaped:

* **Auth** is HTTP Basic with the login name + an *app password* (never the
  account password; Nextcloud's 2FA makes that fail anyway).
* **Every write is conditional.** Updates carry ``If-Match: <etag>``, creates carry
  ``If-None-Match: *``. A 412 means someone (Thunderbird, a phone) changed the
  object since we read it — a ConflictError, never a silent overwrite.
* **A PUT often returns no ETag** (observed: whenever the server rewrote the object
  — scheduling adds SCHEDULE-STATUS). Callers re-read; they never assume.
* **Errors are Sabre XML** (``<s:exception>`` + ``<s:message>``), mapped onto the
  shared taxonomy by status AND body.
* **Reads retry, writes do not.** A 5xx after a PUT may have been applied.
* ``--dry-run`` is enforced HERE, once, for every method that changes state.
"""

from __future__ import annotations

import random
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit

import httpx

from .errors import (
    ApiError,
    AuthError,
    ConflictError,
    DryRun,
    NotFoundError,
    ValidationError,
)

NS = {
    "d": "DAV:",
    "c": "urn:ietf:params:xml:ns:caldav",
    "cs": "http://calendarserver.org/ns/",
    "oc": "http://owncloud.org/ns",
    "nc": "http://nextcloud.com/ns",
    "ical": "http://apple.com/ns/ical/",
    "s": "http://sabredav.org/ns",
}
_XMLNS = " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items() if k != "s")

_WRITE_METHODS = frozenset({"PUT", "DELETE", "MOVE", "COPY", "PROPPATCH", "MKCALENDAR", "MKCOL", "POST"})
_RETRY_STATUS = frozenset({429, 502, 503, 504})
_MAX_ATTEMPTS = 4


def _backoff(attempt: int, retry_after: str | None = None) -> float:
    """Exponential backoff with jitter; a server's Retry-After is a FLOOR, never a
    shortcut (`Retry-After: 0` must not defeat the backoff). Capped at 30 s."""
    delay = 0.5 * 2 ** attempt
    if retry_after and retry_after.strip().isdigit():
        delay = max(delay, float(retry_after))
    return min(delay, 30.0) + random.random() * 0.2


def q(tag: str) -> str:
    """'d:href' -> '{DAV:}href'."""
    prefix, local = tag.split(":", 1)
    return f"{{{NS[prefix]}}}{local}"


@dataclass
class DavResponse:
    """One <d:response> of a multistatus: href, its 200-props, and what 404'd."""

    href: str
    props: dict[str, ET.Element] = field(default_factory=dict)
    missing: set[str] = field(default_factory=set)
    status: int | None = None

    def text(self, tag: str) -> str | None:
        el = self.props.get(q(tag))
        if el is None:
            return None
        return (el.text or "").strip() or None

    def hrefs(self, tag: str) -> list[str]:
        el = self.props.get(q(tag))
        if el is None:
            return []
        return [unquote((h.text or "").strip()) for h in el.findall("d:href", NS)]

    def has(self, tag: str, child: str) -> bool:
        el = self.props.get(q(tag))
        return el is not None and el.find(child, NS) is not None


def _status_code(text: str | None) -> int | None:
    try:
        return int((text or "").split()[1])
    except (IndexError, ValueError):
        return None


def parse_multistatus(body: str) -> list[DavResponse]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ApiError(f"server returned malformed XML: {exc}") from exc
    out: list[DavResponse] = []
    for resp in root.findall("d:response", NS):
        href = unquote(resp.findtext("d:href", default="", namespaces=NS).strip())
        dr = DavResponse(href=href, status=_status_code(resp.findtext("d:status", namespaces=NS)))
        for ps in resp.findall("d:propstat", NS):
            code = _status_code(ps.findtext("d:status", namespaces=NS))
            prop = ps.find("d:prop", NS)
            if prop is None:
                continue
            for el in prop:
                if code == 200:
                    dr.props[el.tag] = el
                else:
                    dr.missing.add(el.tag)
        out.append(dr)
    return out


def _sabre_message(body: str) -> tuple[str | None, str | None]:
    """(exception class, message) from a Sabre error body, if it is one."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None, None
    exc = root.findtext("s:exception", namespaces=NS)
    msg = root.findtext("s:message", namespaces=NS)
    return (exc.rsplit("\\", 1)[-1] if exc else None), (msg.strip() if msg else None)


class Client:
    """A thin wrapper over Nextcloud's CalDAV endpoint (``/remote.php/dav``)."""

    def __init__(
        self,
        base_url: str,
        username: str,
        token: str,
        *,
        verify_ssl: bool = True,
        timeout: float = 30.0,
        dry_run: bool = False,
        user_agent: str = "agent-tool-nextcloud-calendar-cli",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        parts = urlsplit(self.base_url)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.dav_root = f"{self.base_url}/remote.php/dav"
        self.username = username
        self.dry_run = dry_run
        self._client = httpx.Client(
            auth=(username, token),
            verify=verify_ssl,
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": user_agent},
        )

    def close(self) -> None:
        self._client.close()

    # ---- plumbing ----------------------------------------------------

    def url(self, href: str) -> str:
        """A server href (``/remote.php/dav/...``) or absolute URL -> absolute URL."""
        if href.startswith(("http://", "https://")):
            return href
        if href.startswith("/"):
            return self.origin + quote(href, safe="/@:%+")
        return f"{self.dav_root}/{quote(href.lstrip('/'), safe='/@:%+')}"

    def request(
        self,
        method: str,
        href: str,
        *,
        content: str | bytes | None = None,
        headers: dict[str, str] | None = None,
        expect: tuple[int, ...] = (200, 201, 204, 207),
    ) -> httpx.Response:
        url = self.url(href)
        if self.dry_run and method in _WRITE_METHODS:
            body = content.decode() if isinstance(content, bytes) else content
            raise DryRun({"method": method, "url": url, "headers": headers or {}, "body": body})
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._client.request(method, url, content=content, headers=headers)
            except httpx.TransportError as exc:
                # A connect error never reached the server, so even a write is safe
                # to replay. Anything later (read timeout, reset) may have applied a
                # write; replaying that would 412 on If-Match or duplicate a create.
                safe = method not in _WRITE_METHODS or isinstance(exc, httpx.ConnectError)
                if not safe or attempt >= _MAX_ATTEMPTS:
                    raise ApiError(f"{method} {url}: {exc.__class__.__name__}: {exc}") from exc
                time.sleep(_backoff(attempt))
                continue
            # 429 means "not processed", so it is safe to replay for any method;
            # 5xx only for reads (a write may have half-applied).
            retryable = resp.status_code == 429 or (resp.status_code in _RETRY_STATUS and method not in _WRITE_METHODS)
            if retryable and attempt < _MAX_ATTEMPTS:
                time.sleep(_backoff(attempt, resp.headers.get("retry-after")))
                continue
            break
        if resp.status_code in expect:
            return resp
        self._raise(method, url, resp)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _raise(method: str, url: str, resp: httpx.Response) -> None:
        code = resp.status_code
        exc_name, msg = _sabre_message(resp.text)
        text = msg or exc_name or (resp.text[:200].strip() if resp.text else resp.reason_phrase)
        where = f"{method} {urlsplit(url).path}"
        detail = {"status": code, "exception": exc_name} if exc_name else {"status": code}
        if code == 401:
            raise AuthError(
                "the server rejected the login name / app password (401). "
                "Run `nextcloud-calendar auth login` again, or check NEXTCLOUDCALENDAR_USER/NEXTCLOUDCALENDAR_TOKEN.",
                detail=detail,
            )
        if code == 403:
            raise AuthError(f"{where}: forbidden (403): {text}. The calendar may be read-only or shared to you without write access.", detail=detail)
        if code == 404:
            raise NotFoundError(f"{where}: not found (404).", detail=detail)
        if code in (409, 412):
            raise ConflictError(
                f"{where}: the event changed on the server since it was read ({code}: {text}). "
                "Nothing was written. Re-run the command to apply it to the current version.",
                detail=detail,
            )
        if code in (400, 415, 422):
            raise ValidationError(f"{where}: the server refused the data ({code}): {text}", detail=detail)
        if 300 <= code < 400:
            raise ApiError(
                f"{where}: redirected to {resp.headers.get('location')} — the base URL is probably wrong "
                "(use the address you open Nextcloud at, e.g. https://cloud.example.com).",
                status=code,
            )
        raise ApiError(f"{where}: HTTP {code}: {text}", status=code, detail=detail)

    # ---- DAV verbs ---------------------------------------------------

    def propfind(self, href: str, props: str, depth: str = "0") -> list[DavResponse]:
        body = f'<?xml version="1.0" encoding="utf-8"?><d:propfind {_XMLNS}><d:prop>{props}</d:prop></d:propfind>'
        resp = self.request("PROPFIND", href, content=body,
                            headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"})
        return self._multistatus(resp)

    def report(self, href: str, body: str, depth: str = "1") -> list[DavResponse]:
        resp = self.request("REPORT", href, content=body,
                            headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"})
        return self._multistatus(resp)

    @staticmethod
    def _multistatus(resp: httpx.Response) -> list[DavResponse]:
        ctype = resp.headers.get("content-type", "")
        if resp.status_code != 207 or "xml" not in ctype:
            raise ApiError(
                f"expected a WebDAV multistatus, got HTTP {resp.status_code} ({ctype or 'no content-type'}). "
                "Is the base URL your Nextcloud address?",
                status=resp.status_code,
            )
        return parse_multistatus(resp.text)

    def get(self, href: str) -> tuple[str, str | None]:
        resp = self.request("GET", href, headers={"Accept": "text/calendar"}, expect=(200,))
        return resp.text, resp.headers.get("etag")

    def head_etag(self, href: str) -> str | None:
        return self.request("HEAD", href, expect=(200,)).headers.get("etag")

    def put(self, href: str, ics: str, *, etag: str | None = None, create: bool = False) -> str | None:
        """Conditional PUT. Returns the new ETag if the server sent one (often it does not)."""
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if create:
            headers["If-None-Match"] = "*"
        elif etag:
            headers["If-Match"] = etag
        resp = self.request("PUT", href, content=ics.encode("utf-8"), headers=headers, expect=(200, 201, 204))
        return resp.headers.get("etag")

    def delete(self, href: str, *, etag: str | None = None, schedule_reply: bool = True) -> None:
        headers: dict[str, str] = {}
        if etag:
            headers["If-Match"] = etag
        if not schedule_reply:
            # RFC 6638 §8.1: suppress the scheduling message a DELETE would trigger.
            headers["Schedule-Reply"] = "F"
        self.request("DELETE", href, headers=headers, expect=(200, 204))

    def move(self, href: str, destination: str) -> None:
        self.request("MOVE", href, headers={"Destination": self.url(destination), "Overwrite": "F"}, expect=(201, 204))
