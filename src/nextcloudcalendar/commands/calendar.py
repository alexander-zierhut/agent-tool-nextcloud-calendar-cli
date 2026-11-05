"""Calendars: which ones exist, which you can write to."""

from __future__ import annotations

import typer

from ._shared import ctx_obj

app = typer.Typer(no_args_is_help=True)

_COLUMNS = [("ID", "id"), ("Name", "name"), ("Writable", "writable"), ("Owner", "owner"), ("Color", "color")]


@app.command("list")
def list_(ctx: typer.Context) -> None:
    """List your calendars (own and shared with you) that hold events.

    Example: `nextcloud-calendar calendar list`
    Use the `id` with --calendar. `writable: false` = shared to you read-only.
    """
    obj = ctx_obj(ctx)
    dav = obj.dav()
    default = dav.principal().get("defaultCalendar")
    rows = [{**c.to_dict(), "default": c.slug == default} for c in dav.calendars()]
    obj.emitter.emit(rows, columns=_COLUMNS)
