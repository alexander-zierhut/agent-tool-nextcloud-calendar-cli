"""Sticky session defaults, per profile.

context is IMPLICIT state that changes command behaviour. If output looks wrongly
scoped, run `context show` or add `--no-context`. Don't assume a fresh
environment is context-free.
"""

from __future__ import annotations

import typer

from ._shared import ctx_obj

app = typer.Typer(no_args_is_help=True)

# Every key must be the dest of a real `--<key>` OPTION somewhere in the tree
# (tests/test_globals_unit.py proves it); context fills options, never arguments.
KNOWN_KEYS = ["calendar"]


@app.command("show")
def show(ctx: typer.Context) -> None:
    """Print the active context, whether it applies, and where it is stored."""
    from ..config import config_path

    from ..spec import SPEC

    obj = ctx_obj(ctx)
    current = obj.config.context
    obj.emitter.emit({
        "profile": obj.config.active_profile_name(),
        "context": current,
        # False when empty or switched off for this run (--no-context / env).
        "applies": bool(current) and SPEC.getenv("NO_CONTEXT") != "1",
        "knownKeys": KNOWN_KEYS,
        "configPath": str(config_path()),
    })


@app.command("set")
def set_(ctx: typer.Context, calendar: str = typer.Option(None, "--calendar", help="Default --calendar for every command.")) -> None:
    """Set sticky defaults, e.g. `context set --calendar work`."""
    from ..config import Config
    from ..errors import ValidationError

    if calendar is None:
        raise ValidationError("nothing to set. Example: `nextcloud-calendar context set --calendar personal`.")
    if not calendar.strip():
        raise ValidationError("--calendar must not be empty; use `context clear` to remove it.")
    obj = ctx_obj(ctx)
    cfg = Config.load()  # reload before save: the in-memory copy may be stale
    name = cfg.active_profile_name()
    cur = dict(cfg.contexts.get(name) or {})
    cur["calendar"] = calendar
    cfg.contexts[name] = cur
    cfg.save()
    obj.emitter.emit({"profile": name, "context": cur})


@app.command("clear")
def clear(ctx: typer.Context) -> None:
    """Remove every sticky default for the active profile."""
    from ..config import Config

    obj = ctx_obj(ctx)
    cfg = Config.load()
    cfg.contexts.pop(cfg.active_profile_name(), None)
    cfg.save()
    obj.emitter.emit({"cleared": True, "context": {}})
