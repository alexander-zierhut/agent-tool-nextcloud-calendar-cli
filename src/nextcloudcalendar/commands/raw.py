"""The escape hatch: any WebDAV/CalDAV request (still authenticated, error-mapped, dry-run aware)."""

from __future__ import annotations

from pathlib import Path

import typer

from ..client import parse_multistatus
from ._shared import ctx_obj

app = typer.Typer(no_args_is_help=True)


def _body(data: str | None, file: str | None) -> str | None:
    if file:
        return Path(file).read_text(encoding="utf-8")
    return data


def _props(resps) -> list[dict]:
    out = []
    for r in resps:
        props = {}
        for tag, el in r.props.items():
            local = tag.split("}", 1)[-1]
            hrefs = [h.text for h in el.iter() if h.tag.endswith("}href") and h.text]
            props[local] = hrefs if hrefs else ((el.text or "").strip() or [c.tag.split("}", 1)[-1] for c in el] or None)
        out.append({"href": r.href, "props": props, "missing": sorted(t.split("}", 1)[-1] for t in r.missing)})
    return out


@app.command("get")
def get(ctx: typer.Context, href: str = typer.Argument(..., help="Server path, e.g. /remote.php/dav/calendars/<user>/personal/x.ics")) -> None:
    """GET a resource; returns its body and ETag. Example: `raw get /remote.php/dav/calendars/alex/personal/x.ics`."""
    obj = ctx_obj(ctx)
    resp = obj.client().request("GET", href, expect=(200,))
    obj.emitter.emit({"href": href, "etag": resp.headers.get("etag"), "contentType": resp.headers.get("content-type"), "body": resp.text})


@app.command("propfind")
def propfind(
    ctx: typer.Context,
    href: str = typer.Argument(...),
    props: str = typer.Option("<d:displayname/><d:resourcetype/><d:getetag/>", "--props", help="Inner <d:prop> XML (prefixes d c cs oc nc ical are declared)."),
    depth: str = typer.Option("1", "--depth", help="0, 1 (default) or infinity."),
) -> None:
    """PROPFIND with your own property list; parsed into JSON."""
    obj = ctx_obj(ctx)
    obj.emitter.emit(_props(obj.client().propfind(href, props, depth=depth)))


@app.command("report")
def report(
    ctx: typer.Context,
    href: str = typer.Argument(...),
    data: str = typer.Option(None, "--data", help="The full REPORT XML body."),
    file: str = typer.Option(None, "--file", help="Read the REPORT body from a file."),
    depth: str = typer.Option("1", "--depth"),
) -> None:
    """REPORT (calendar-query, sync-collection, ...); parsed into JSON."""
    obj = ctx_obj(ctx)
    resp = obj.client().request("REPORT", href, content=_body(data, file),
                                headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"})
    obj.emitter.emit(_props(parse_multistatus(resp.text)))


@app.command("put")
def put(
    ctx: typer.Context,
    href: str = typer.Argument(...),
    file: str = typer.Option(None, "--file", help="The .ics to upload."),
    data: str = typer.Option(None, "--data", help="The body inline."),
    etag: str = typer.Option(None, "--if-match", help="Only overwrite this version (recommended)."),
) -> None:
    """PUT raw iCalendar. WARNING: bypasses the quiet-write rules — the server may e-mail attendees."""
    obj = ctx_obj(ctx)
    headers = {"Content-Type": "text/calendar; charset=utf-8"}
    if etag:
        headers["If-Match"] = etag
    resp = obj.client().request("PUT", href, content=(_body(data, file) or "").encode(), headers=headers)
    obj.emitter.emit({"href": href, "status": resp.status_code, "etag": resp.headers.get("etag")})


@app.command("delete")
def delete(
    ctx: typer.Context,
    href: str = typer.Argument(...),
    etag: str = typer.Option(None, "--if-match"),
    no_reply: bool = typer.Option(False, "--no-schedule-reply", help="Send `Schedule-Reply: F` (no cancellation mails)."),
) -> None:
    """DELETE a resource. Without --no-schedule-reply the server may mail CANCEL/REPLY."""
    obj = ctx_obj(ctx)
    obj.client().delete(href, etag=etag, schedule_reply=not no_reply)
    obj.emitter.emit({"href": href, "deleted": True})
