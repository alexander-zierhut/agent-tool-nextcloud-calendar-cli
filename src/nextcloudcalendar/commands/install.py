"""`nextcloud-calendar install claude` — register this CLI with Claude Code as a Skill.

Machinery is verbatim from the sibling CLIs (same function names — `appctx.py`'s
first-run offer calls them by name). What's fresh is `SKILL_MD`: every trigger is
anchored to the calendar ("Nextcloud calendar", "Termin", "Einladung"), German
verbs only together with an appointment noun, and only commands that exist are named.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from .. import __version__
from ..errors import OpError
from ._shared import ctx_obj

app = typer.Typer(no_args_is_help=True)

SKILL_NAME = "nextcloud-calendar"
_MEM_START = "<!-- nextcloud-calendar:start -->"
_MEM_END = "<!-- nextcloud-calendar:end -->"

SKILL_MD = f"""\
---
name: nextcloud-calendar
description: >-
  Work with the user's Nextcloud calendar (CalDAV) via the `nextcloud-calendar`
  command — list Nextcloud calendar appointments (Termine) in a time window,
  move or reschedule a Termin or one occurrence of a recurring meeting, lengthen
  or shorten a meeting, cancel or delete a Termin, accept or decline a meeting
  invitation (Einladung), apply an invitation e-mail (.ics/.eml) to the
  calendar, restore a deleted Termin from the calendar trash, and repair
  recurring meetings that show twice or vanished in Thunderbird. Use this
  whenever the user mentions their Nextcloud calendar, Kalender or Termine, asks
  what is in their calendar, or asks to move/postpone/extend/cancel/accept/decline
  a specific Termin, Meeting, Besprechung or Einladung ("verschieb den Termin",
  "sag das Meeting ab", "verlängere die Besprechung", "nimm die Einladung an").
  Not for writing e-mails about appointments.
---

# Nextcloud calendar CLI (agent-tool-nextcloud-calendar-cli v{__version__})

The `nextcloud-calendar` command is installed on this machine and edits the
user's Nextcloud calendars on the server (what Thunderbird, phone and web
show). Prefer it over reading Thunderbird's files.

## Start here: quiet by default
Every write changes ONLY the user's calendar and e-mails nobody. Add `--notify`
only when the user wants the other people told (decline to the organizer,
send an update/cancellation as organizer). Each write returns `mailed` = who the
server actually e-mailed; report it to the user. Exit 8 = that exact wish is
impossible; the message says what is possible: relay it, don't work around it.

    nextcloud-calendar event list --from mon --days 5          # what's coming
    nextcloud-calendar event list --search "Weekly" --days 60  # find an event
    nextcloud-calendar event move "Team Weekly" --occurrence 2026-11-06 --to 11:30
    nextcloud-calendar event update ID --occurrence fri --duration 2h30m
    nextcloud-calendar event update ID --extend +1h
    nextcloud-calendar event cancel ID --occurrence 2026-11-20  # stays, struck through
    nextcloud-calendar event respond ID declined --notify      # tell the organizer
    nextcloud-calendar event delete ID --occurrence 2026-11-20 # -> trash, restorable
    nextcloud-calendar event create --title "X" --start "fri 14:00" --duration 45m
    nextcloud-calendar event import ~/Downloads/invite.eml --accept
    nextcloud-calendar diagnose --fix                          # duplicated/vanished occurrences
    nextcloud-calendar trash list

## Learn the tool from the tool
`nextcloud-calendar guide` is the built-in manual (offline, no login needed).
Topics: scheduling · recurring · times · diagnose · import · auth · context ·
settings · output · gotchas. Read `nextcloud-calendar guide scheduling` before
any --notify. Every command has `--help`.

## Commands
- `nextcloud-calendar event list|get|create|move|update|respond|cancel|delete|import`
- `nextcloud-calendar calendar list` — calendar ids for --calendar.
- `nextcloud-calendar diagnose [--fix]` — series that Thunderbird shows twice / not at all.
- `nextcloud-calendar trash list|restore|purge` — undo deletions.
- `nextcloud-calendar auth login|status|profiles|whoami|logout`
- `nextcloud-calendar raw get|propfind|report|put|delete` — escape hatch (raw put/delete bypass the quiet rules).
- `nextcloud-calendar settings`, `nextcloud-calendar context`, `nextcloud-calendar report`.

## How to refer to events
Use the `id` (calendar/file.ics) from `event list` once you have it. A title
works too but is refused when ambiguous (exit 7 lists candidates with ids).
Recurring events need `--occurrence DATE` (one) or `--series` (all): ask the
user if the request does not make it clear. Times are the user's local zone;
"11:30" means 11:30 on the occurrence's own day.

## Output contract
- Default output is JSON on stdout: parse it.
- Errors are JSON on stderr with a non-zero exit code.
- Trim with `--fields start,summary,id`; `--stream` for NDJSON; `-o table` for humans.

## Exit codes
`0` ok · `1` generic · `2` usage · `3` config · `4` auth · `5` not found ·
`6` changed on the server meanwhile (re-run) · `7` validation / ambiguous ·
`8` scheduling refused (quiet/notify not possible as asked) · `20` findings with
`diagnose --exit-code` (findings alone exit 0) · `130` interrupted.

## Auth
If not configured, ask the user to run `nextcloud-calendar auth login --url
https://<their-nextcloud> --web` (browser approval, app password into the keyring),
or set NEXTCLOUDCALENDAR_URL + NEXTCLOUDCALENDAR_USER + NEXTCLOUDCALENDAR_TOKEN.
Never ask for or handle the password yourself. `nextcloud-calendar auth status`
names which login/backend is actually in use.

## Make changes safely
Preview ANY write with a global `--dry-run`. Deleting, cancelling and anything
with `--notify` (it e-mails other people) — confirm with the user first unless
they asked for exactly that.

## Gotchas that bite once
- "Sag ab" depends on the role: the user ORGANISES it -> `event cancel`
  (`--notify` to tell attendees); someone else does -> `event respond ID declined`
  (`--notify` to tell the organizer). `role` is in every event row.
- An attendee cannot send a new time to the organizer; moving someone else's
  meeting changes the user's calendar only. Say so.
- Changing ONE occurrence of a series the user ORGANISES always mails everyone
  on Nextcloud: the tool refuses that quietly (exit 8); ask whether to --notify.
- Exit 6 = someone synced in between; nothing was written, just re-run.
- A sticky default calendar (`nextcloud-calendar context show`) scopes commands.
- Thunderbird shows changes after its next sync.

## Reporting a problem — open an issue
If `nextcloud-calendar` made a task painful, missing, or impossible **and the user asks you to file it**, open a GitHub issue on this tool's repo (only when asked; one issue per problem; check for a duplicate first):
First run `nextcloud-calendar report` — it prints the repo and a pre-filled issue link (offline, no token), which is also what an installed user sees when there's no skill.
```bash
gh issue create --repo alexander-zierhut/agent-tool-nextcloud-calendar-cli \\
  --title "<summary>" --body "<goal · exact command(s) · error + exit code · `nextcloud-calendar --version` · suggested fix>"
```
No `gh` / not authed? Give the user the prefilled link: `https://github.com/alexander-zierhut/agent-tool-nextcloud-calendar-cli/issues/new`.
"""

_MEMORY_HINT = (
    f"{_MEM_START}\n"
    "The `nextcloud-calendar` CLI (package agent-tool-nextcloud-calendar-cli) is installed — "
    "an agent-ready Nextcloud calendar client with JSON output; it edits the user's calendar "
    "directly (quiet by default, --notify to mail). "
    "Run `nextcloud-calendar guide` to learn it.\n"
    f"{_MEM_END}\n"
)


def claude_available() -> bool:
    if shutil.which("claude"):
        return True
    home = Path.home()
    return (home / ".claude").is_dir() or (home / ".local" / "bin" / "claude").exists()


def _skill_dir(project: bool) -> Path:
    base = Path.cwd() if project else Path.home()
    return base / ".claude" / "skills" / SKILL_NAME


def skill_installed(project: bool = False) -> bool:
    return (_skill_dir(project) / "SKILL.md").exists()


def write_skill(project: bool = False) -> Path:
    d = _skill_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "SKILL.md"
    path.write_text(SKILL_MD, encoding="utf-8")
    return path


def _memory_file() -> Path:
    return Path.home() / ".claude" / "CLAUDE.md"


def write_memory_hint() -> Path:
    path = _memory_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _MEM_START in existing:
        return path
    sep = "" if existing.endswith("\n") or not existing else "\n"
    path.write_text(existing + sep + "\n" + _MEMORY_HINT, encoding="utf-8")
    return path


def _remove_memory_hint() -> bool:
    path = _memory_file()
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if _MEM_START not in text or _MEM_END not in text:
        return False
    before, _, rest = text.partition(_MEM_START)
    _, _, after = rest.partition(_MEM_END)
    path.write_text((before.rstrip("\n") + "\n" + after.lstrip("\n")).strip("\n") + "\n", encoding="utf-8")
    return True


@app.command()
def claude(
    ctx: typer.Context,
    project: bool = typer.Option(False, "--project", help="Install into ./.claude instead of ~/.claude."),
    memory: bool = typer.Option(False, "--memory", help="Also add a one-line hint to ~/.claude/CLAUDE.md."),
    force: bool = typer.Option(False, "--force", help="Install even if Claude Code isn't detected."),
    uninstall: bool = typer.Option(False, "--uninstall", help="Remove the skill (and memory hint)."),
    print_: bool = typer.Option(False, "--print", help="Print the SKILL.md that would be written and exit."),
) -> None:
    """Register `nextcloud-calendar` with Claude Code as a Skill. Reversible with --uninstall."""
    obj = ctx_obj(ctx)
    if print_:
        typer.echo(SKILL_MD)
        return
    if uninstall:
        d = _skill_dir(project)
        removed = []
        if (d / "SKILL.md").exists():
            (d / "SKILL.md").unlink()
            try:
                d.rmdir()
            except OSError:
                pass
            removed.append(str(d))
        if _remove_memory_hint():
            removed.append(str(_memory_file()) + " (hint)")
        obj.emitter.emit({"status": "uninstalled", "removed": removed})
        return
    if not force and not claude_available():
        raise OpError(
            "Claude Code was not detected. Install it from https://claude.com/claude-code, "
            "or re-run with --force."
        )
    skill_path = write_skill(project)
    result = {"status": "installed", "skill": str(skill_path), "scope": "project" if project else "user"}
    if memory:
        result["memoryHint"] = str(write_memory_hint())
    obj.emitter.emit(result)
