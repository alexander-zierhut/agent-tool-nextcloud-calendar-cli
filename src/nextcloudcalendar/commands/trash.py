"""Nextcloud's calendar trash bin: everything deleted, restorable for 30 days."""

from __future__ import annotations

import typer

from ._shared import ctx_obj

app = typer.Typer(no_args_is_help=True)

_COLUMNS = [("ID", "id"), ("Deleted", "deletedAt"), ("Calendar", "calendar"), ("Summary", "summary"), ("Start", "start")]


@app.command("list")
def list_(ctx: typer.Context) -> None:
    """List deleted events, newest first.

    Example: `nextcloud-calendar trash list`
    Deleting in Thunderbird, on a phone or with `event delete` all land here.
    """
    obj = ctx_obj(ctx)
    obj.emitter.emit(obj.dav().trash(), columns=_COLUMNS)


@app.command("restore")
def restore(ctx: typer.Context, trash_id: str = typer.Argument(..., help="The `id` from `trash list`.")) -> None:
    """Put a deleted event back into its calendar. Sends no e-mail (observed).

    Example: `nextcloud-calendar trash restore 19.ics`
    """
    obj = ctx_obj(ctx)
    item = obj.dav().restore(trash_id)
    obj.emitter.emit({"restored": True, **item})


@app.command("purge")
def purge(ctx: typer.Context, trash_id: str = typer.Argument(..., help="The `id` from `trash list`.")) -> None:
    """Delete a trash entry for good (cannot be undone).

    Example: `nextcloud-calendar trash purge 19.ics`
    Needed only when Nextcloud refuses a delete because an older deleted copy
    with the same name is in the trash (`event delete` handles that itself).
    """
    obj = ctx_obj(ctx)
    item = obj.dav().purge(trash_id)
    obj.emitter.emit({"purged": True, **item})
