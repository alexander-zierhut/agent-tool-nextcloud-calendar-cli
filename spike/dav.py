"""Throwaway probe helpers for the spike. Not the product's transport."""

from __future__ import annotations

import json
import os
import textwrap
import xml.etree.ElementTree as ET

import httpx

BASE = os.environ.get("NC_URL", "http://127.0.0.1:8089")
MAILPIT = os.environ.get("MAILPIT_URL", "http://127.0.0.1:8025")
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "cs": "http://calendarserver.org/ns/",
      "oc": "http://owncloud.org/ns", "nc": "http://nextcloud.com/ns", "ical": "http://apple.com/ns/ical/"}


def client(user: str) -> httpx.Client:
    return httpx.Client(base_url=BASE, auth=(user, f"test-pw-{user}-123456"), timeout=30)


def show(r: httpx.Response, body: bool = True, limit: int = 1500) -> None:
    hdr = {k: v for k, v in r.headers.items() if k.lower() in ("etag", "location", "content-type", "dav", "schedule-tag")}
    print(f"  -> {r.request.method} {r.request.url.path} = {r.status_code} {hdr}")
    if body and r.text:
        print(textwrap.indent(r.text[:limit], "     "))


def propfind(c: httpx.Client, path: str, props: str, depth: str = "0") -> httpx.Response:
    xmlns = " ".join('xmlns:%s="%s"' % kv for kv in NS.items())
    body = f'<?xml version="1.0"?><d:propfind {xmlns}><d:prop>{props}</d:prop></d:propfind>'
    return c.request("PROPFIND", path, content=body, headers={"Depth": depth, "Content-Type": "application/xml"})


def report(c: httpx.Client, path: str, body: str, depth: str = "1") -> httpx.Response:
    return c.request("REPORT", path, content=body, headers={"Depth": depth, "Content-Type": "application/xml"})


def put(c: httpx.Client, path: str, ics: str, **headers) -> httpx.Response:
    h = {"Content-Type": "text/calendar; charset=utf-8"}
    h.update({k.replace("_", "-"): v for k, v in headers.items()})
    return c.put(path, content=ics.replace("\n", "\r\n"), headers=h)


def mails(clear: bool = True) -> list[dict]:
    r = httpx.get(f"{MAILPIT}/api/v1/messages").json()
    out = []
    for m in r.get("messages", []):
        full = httpx.get(f"{MAILPIT}/api/v1/message/{m['ID']}").json()
        method = None
        for a in full.get("Attachments", []) + full.get("Inline", []):
            if "calendar" in a.get("ContentType", ""):
                raw = httpx.get(f"{MAILPIT}/api/v1/message/{m['ID']}/part/{a['PartID']}").text
                method = next((ln for ln in raw.splitlines() if ln.startswith("METHOD")), None)
        out.append({"to": [t["Address"] for t in m["To"]], "subject": m["Subject"], "method": method})
    if clear:
        httpx.delete(f"{MAILPIT}/api/v1/messages")
    return out


def print_mails(label: str = "") -> list[dict]:
    ms = mails()
    print(f"  MAILS{(' ' + label) if label else ''}: {json.dumps(ms, ensure_ascii=False) if ms else 'none'}")
    return ms


def reset(*users: str) -> None:
    """Delete every object in each user's personal calendar (spike hygiene)."""
    for u in users:
        c = client(u)
        r = propfind(c, f"/remote.php/dav/calendars/{u}/personal/", "<d:getetag/>", "1")
        for href, _, _ in hrefs_with_data(r.text):
            if href.endswith(".ics"):
                c.delete(href, headers={"Schedule-Reply": "F"})
    mails()


def hrefs_with_data(xml: str) -> list[tuple[str, str, str]]:
    root = ET.fromstring(xml)
    out = []
    for resp in root.findall("d:response", NS):
        href = resp.findtext("d:href", namespaces=NS)
        etag = resp.findtext(".//d:getetag", namespaces=NS)
        data = resp.findtext(".//c:calendar-data", namespaces=NS) or ""
        out.append((href, etag, data))
    return out
