"""Top-level Typer application."""

from __future__ import annotations

import os
import sys

import typer
from agentcli import OutputFormat, print_error
from agentcli.errors import DryRun, OpError

from . import __version__
from .appctx import AppContext


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


app = typer.Typer(
    name="nextcloud-calendar",
    help=(
        "Agent-friendly CLI for Nextcloud calendars (CalDAV): list, move, extend, cancel and "
        "answer appointments, and repair recurring meetings that show twice or vanished. "
        "Quiet by default: nobody is e-mailed unless you pass --notify.\n\n"
        "Output is JSON on stdout by default (errors are JSON on stderr with a non-zero exit "
        "code); add `-o table` or trim with `--fields`.\n\n"
        "New here / no context? Run `nextcloud-calendar guide` for the full playbook."
    ),
    epilog="Learn more:  `nextcloud-calendar guide`  ·  `nextcloud-calendar guide scheduling`",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,  # locals hold the app password
)

_ERROR_FORMAT = OutputFormat.json
_META = ("settings", "guide", "install", "context", "report")
# Commands that ignore the sticky context: the meta commands, plus the ones you
# run to diagnose or recover. A saved default calendar silently rescoping a
# diagnostic is the last thing you want when you are already lost.
_NO_CONTEXT = (*_META, "auth", "diagnose", "trash", "raw")


def _context_default_map(cmd, context: dict, skip: set[str]) -> dict:
    """Context -> Click default_map, OPTIONS ONLY. Arguments are never filled from
    sticky state: a forgotten required argument must fail, not hit the wrong event."""
    out: dict = {}
    for name, sub in (getattr(cmd, "commands", None) or {}).items():
        if name in skip:
            continue
        if getattr(sub, "commands", None):
            nested = _context_default_map(sub, context, skip)
            if nested:
                out[name] = nested
            continue
        opt_names = {p.name for p in sub.params if getattr(p, "param_type_name", "") == "option"}
        hit = {k: v for k, v in context.items() if k in opt_names}
        if hit:
            out[name] = hit
    return out


@app.callback()
def _root(
    ctx: typer.Context,
    output: OutputFormat = typer.Option(None, "--output", "-o", help="json (default), table, markdown, csv. Also --format/-f, anywhere on the line."),
    fields: str = typer.Option(None, "--fields", "--columns", help="Comma-separated fields, e.g. 'start,summary,id'. Anywhere on the line."),
    profile: str = typer.Option(None, "--profile", "-p", help="Configuration profile."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Writes: print the request that would be sent and exit 0."),
    stream: bool = typer.Option(False, "--stream", help="Stream list results as NDJSON."),
    no_context: bool = typer.Option(False, "--no-context", help="Ignore the saved session context for this command."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable coloured output."),
    version: bool = typer.Option(None, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit."),
) -> None:
    if profile:
        os.environ["NEXTCLOUDCALENDAR_PROFILE"] = profile
    meta = ctx.invoked_subcommand in _META
    interactive = not meta and sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("CI") != "true"
    ctx.obj = AppContext(output=output, color=not no_color, interactive=interactive)
    global _ERROR_FORMAT
    _ERROR_FORMAT = ctx.obj.emitter.fmt
    if ctx.invoked_subcommand not in _NO_CONTEXT and os.environ.get("NEXTCLOUDCALENDAR_NO_CONTEXT") != "1" and ctx.obj.config.context:
        dm = _context_default_map(ctx.command, ctx.obj.config.context, skip=set(_NO_CONTEXT))
        ctx.default_map = {**(ctx.default_map or {}), **dm}


_FORMAT_FLAGS = ("--format", "-f", "--output", "-o")
_FIELDS_FLAGS = ("--fields", "--columns")
_BOOL_FLAGS = ("--dry-run", "--stream", "--no-context")


def _pop_globals(argv: list[str]) -> tuple[str | None, str | None, set[str], list[str]]:
    out: list[str] = []
    fmt: str | None = None
    fields: str | None = None
    bools: set[str] = set()
    i, stop = 0, False

    def take(idx):
        return (argv[idx + 1], idx + 1) if idx + 1 < len(argv) else (None, idx)

    while i < len(argv):
        a = argv[i]
        if not stop and a == "--":
            stop = True
            out.append(a)
        elif not stop and a in _FORMAT_FLAGS:
            fmt, i = take(i)
        elif not stop and a in _FIELDS_FLAGS:
            fields, i = take(i)
        elif not stop and a in _BOOL_FLAGS:
            bools.add(a.lstrip("-"))
        elif not stop and any(a.startswith(p + "=") for p in _FORMAT_FLAGS):
            fmt = a.split("=", 1)[1]
        elif not stop and any(a.startswith(p + "=") for p in _FIELDS_FLAGS):
            fields = a.split("=", 1)[1]
        else:
            out.append(a)
        i += 1
    return fmt, fields, bools, out


# ---- command groups (imported here to avoid circular imports) ----
from .commands import (  # noqa: E402
    auth,
    calendar,
    diagnose,
    event,
    guide,
    install,
    raw,
    report,
    settings,
    trash,
)
from .commands import context as context_cmd  # noqa: E402

app.command("guide", help="Built-in operating guide — how to use this CLI without external docs.")(guide.guide)
app.command("report", help="Report a bug or missing feature — prints this tool's repo and a pre-filled issue link (offline, no token).")(report.report)
app.add_typer(event.app, name="event", help="Events: list, get, create, move, update, respond, cancel, delete, import.")
app.command("diagnose", help="Find (and --fix) recurring events that show twice or vanished in some clients.")(diagnose.diagnose)
app.add_typer(calendar.app, name="calendar", help="Your calendars and their ids.")
app.add_typer(trash.app, name="trash", help="Deleted events: list, restore, purge.")
app.add_typer(auth.app, name="auth", help="Log in (browser flow or app password), status, whoami, log out.")
app.add_typer(raw.app, name="raw", help="Escape hatch: any WebDAV/CalDAV request.")
app.add_typer(settings.app, name="settings", help="View & change CLI settings.")
app.add_typer(context_cmd.app, name="context", help="Sticky session defaults (e.g. a default --calendar), per profile.")
app.add_typer(install.app, name="install", help="Integrate with other tools (e.g. `install claude`).")


def main() -> None:
    import json as _json

    fmt, fields, bools, argv = _pop_globals(sys.argv[1:])
    if fmt is not None:
        os.environ["NEXTCLOUDCALENDAR_CLI_FORMAT"] = fmt
    if fields is not None:
        os.environ["NEXTCLOUDCALENDAR_CLI_FIELDS"] = fields
    if "dry-run" in bools:
        os.environ["NEXTCLOUDCALENDAR_DRY_RUN"] = "1"
    if "stream" in bools:
        os.environ["NEXTCLOUDCALENDAR_STREAM"] = "1"
    if "no-context" in bools:
        os.environ["NEXTCLOUDCALENDAR_NO_CONTEXT"] = "1"
    try:
        app(args=argv)
    except DryRun as dr:
        sys.stdout.write(_json.dumps({"dryRun": True, "request": dr.request}, indent=2, default=str) + "\n")
        sys.exit(0)
    except OpError as exc:
        print_error(exc, _ERROR_FORMAT)
        sys.exit(exc.exit_code)
    except ValueError as exc:
        print_error(OpError(str(exc)), _ERROR_FORMAT)
        sys.exit(1)
    except KeyboardInterrupt:  # pragma: no cover
        print_error(OpError("interrupted"), _ERROR_FORMAT)
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
