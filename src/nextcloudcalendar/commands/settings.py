"""`nextcloud-calendar settings` — every setting has a sane default or is asked once.

The one stored setting is `default_format` (asked once, interactively, on first
run; see `appctx`). Per-profile values (address, user, time zone, default
calendar) are written by `auth login`; sticky defaults live in `context`.
"""

from __future__ import annotations

import typer
from agentcli import OutputFormat

from ..config import Config, config_path
from ..errors import OpError
from ..spec import SPEC, credentials
from ._shared import ctx_obj

app = typer.Typer(no_args_is_help=True)


@app.command()
def show(ctx: typer.Context) -> None:
    """Show every setting, its value, and where it came from."""
    obj = ctx_obj(ctx)
    cfg: Config = obj.config
    obj.emitter.emit(
        {
            "defaultFormat": cfg.default_format or "json (default — not yet chosen)",
            "activeProfile": cfg.active_profile_name(),
            "credentialBackend": credentials.backend_name(),
            "configPath": str(config_path()),
        }
    )


@app.command("set-format")
def set_format(
    ctx: typer.Context,
    fmt: str = typer.Argument(..., help="json | table | markdown | csv"),
) -> None:
    """Set the default output format."""
    obj = ctx_obj(ctx)
    try:
        chosen = OutputFormat.coerce(fmt)
    except ValueError as exc:
        raise OpError(str(exc)) from exc
    # Reload before save: another shell may have logged in since this process
    # read the config, and writing our stale copy back would drop that profile.
    cfg = Config.load()
    cfg.default_format = chosen.value
    cfg.save()
    obj.emitter.emit({"status": "saved", "defaultFormat": chosen.value, "configPath": str(config_path())})


@app.command()
def path(ctx: typer.Context) -> None:
    """Print the config file path."""
    ctx_obj(ctx).emitter.emit({"configPath": str(config_path()), "configDir": str(SPEC.config_dir())})
