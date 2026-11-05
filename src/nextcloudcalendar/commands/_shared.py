"""Helpers shared by command modules."""

from __future__ import annotations

import typer

from ..appctx import AppContext


def ctx_obj(ctx: typer.Context) -> AppContext:
    obj = getattr(ctx, "obj", None)
    if obj is None:
        obj = AppContext()
        ctx.obj = obj
    return obj


CALENDAR_OPT_HELP = "Calendar id or name (see `calendar list`). Default: all calendars for lookups, your default calendar for new events."
NOTIFY_HELP = (
    "Let the server e-mail the other people on the event (organizer or attendees). "
    "Default is QUIET: only your calendar changes and nobody is mailed."
)
