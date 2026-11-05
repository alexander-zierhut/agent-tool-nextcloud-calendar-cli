"""`nextcloud-calendar guide` — the built-in manual. Zero config, zero auth, offline."""

from __future__ import annotations

import typer

OVERVIEW = """\
nextcloud-calendar — operating guide (run `nextcloud-calendar guide <topic>` for details)

WHAT IT IS
  Read and change events in your Nextcloud calendars directly on the server:
  the same data Thunderbird, phones and the web UI show. It can do what calendar
  apps refuse: move or lengthen a meeting someone else organised (in YOUR
  calendar only), cancel without e-mailing anyone, and repair series that show
  occurrences twice or not at all.

OUTPUT CONTRACT
  - stdout is JSON. Errors are JSON on stderr with a non-zero exit code:
    {"error": "...", "detail": {...}}
  - Exit codes: 0 ok · 1 generic · 3 config · 4 auth · 5 not-found · 6 conflict
                (changed on the server meanwhile: re-run) · 7 validation/ambiguous ·
                8 scheduling refused · 130 interrupted.
  - `-o table|markdown|csv`, `--fields a,b`, `--stream`, `--dry-run` (preview writes).
  - Findings are not failures: `diagnose` exits 0 even when it finds broken
    series; add `--exit-code` to get exit 20 when it does.
  - Every write reports `mailed` (who the SERVER e-mailed), read back from the
    server's own SCHEDULE-STATUS, not a guess.

AUTHENTICATE
  Interactive:   nextcloud-calendar auth login --url https://cloud.example.com --web
                 (browser approval; the app password goes to the OS keyring)
  Headless:      export NEXTCLOUDCALENDAR_URL=https://cloud.example.com
                 export NEXTCLOUDCALENDAR_USER=alex
                 export NEXTCLOUDCALENDAR_TOKEN=xxxxx-xxxxx   # an app password
  Check:         nextcloud-calendar auth status

QUIET BY DEFAULT  (read `guide scheduling` before using --notify)
  Writes change only your calendar; nobody is mailed. --notify lets the server
  e-mail the other people. Where neither can be honoured exactly, the command
  refuses with exit 8 and says what is possible.

FIND THINGS
  `nextcloud-calendar event list` (today + 6 days), --from/--to/--days, --search
  Every row has `id` (calendar/file.ics) and, for recurring events, `occurrence`.
  Commands take an id, a UID or a title; ambiguous titles are refused with the
  candidates listed (exit 7): pass the id then.
  `nextcloud-calendar calendar list` shows the calendars (--calendar takes the id).

CHANGE THINGS
  `nextcloud-calendar event move REF --to 11:30 [--occurrence DATE | --series]`
  `nextcloud-calendar event update REF --duration 2h30m | --extend +1h | --end 14:00`
  `nextcloud-calendar event respond REF declined [--notify]`
  `nextcloud-calendar event cancel REF` (stays visible, struck through)
  `nextcloud-calendar event delete REF [--occurrence DATE]` (-> trash, restorable)
  `nextcloud-calendar event create --title T --start "fri 14:00" --duration 45m`
  `nextcloud-calendar event import invite.eml --accept` (apply an invitation mail)

REPAIR
  `nextcloud-calendar diagnose` finds series that clients show differently
  (moved occurrence shown twice, or vanished); `--fix` repairs quietly.
  `nextcloud-calendar trash list` / `trash restore ID` undo deletions.

DISCOVER COMMANDS & OPTIONS
  nextcloud-calendar --help
  nextcloud-calendar <group> --help              e.g. `nextcloud-calendar event --help`
  nextcloud-calendar <group> <command> --help    e.g. `nextcloud-calendar event move --help`

USE WITH CLAUDE CODE
  `nextcloud-calendar install claude` registers a Claude Code skill so Claude
  auto-uses this CLI whenever you mention your calendar. (`--print` to preview,
  `--uninstall` to remove.)

KEY GOTCHAS  (each one saves a failed round-trip)
  - A recurring event needs --occurrence DATE or --series; neither is assumed.
  - "11:30" means 11:30 on the occurrence's own day, in your zone.
  - You cannot tell an organizer about a NEW TIME through the server (iTIP has no
    way); move it quietly in your calendar, and write them if needed.
  - Thunderbird caches: changes appear there after its next sync.
  - A sticky default calendar (`context`) silently scopes commands; see `guide context`.

TOPICS:  scheduling · recurring · times · diagnose · import · auth · context · settings · output · gotchas
"""

TOPICS: dict[str, str] = {
    "scheduling": """\
SCHEDULING — who gets e-mailed, measured against Nextcloud 35 with a mail catcher

Your role decides what the server may send. `role` is in every event row:
  personal   nobody else on it         -> never mails
  attendee   someone else organises    -> server could REPLY to the organizer
  organizer  you organise, others come -> server could REQUEST/CANCEL to attendees

QUIET (default)
  attendee : the tool sets ORGANIZER;SCHEDULE-AGENT=CLIENT (server scheduling
             off for that event, exactly how Thunderbird stores e-mailed invites).
             Move, extend, cancel, delete, answer: nothing is sent.
  organizer: SEQUENCE and LAST-MODIFIED are kept, so Nextcloud does not mail.
             Move/extend/cancel the whole event or series, delete one occurrence
             (`event delete --occurrence`), delete the event: no mail. Colleagues
             with an account on the same Nextcloud see the change in their
             calendar (server-side delivery, not mail).
             REFUSED (exit 8): changing ONE occurrence of a series you organise —
             Nextcloud always mails everyone about that. Use --notify, or --series.

--notify
  attendee : `event respond ... --notify` mails your answer (REPLY) to the
             organizer; `event delete --notify` declines first. A new time cannot
             be sent (exit 8).
  organizer: SEQUENCE is raised -> the server mails the update / cancellation.

VERIFY
  `mailed` lists who the server actually mailed (SCHEDULE-STATUS 1.1, read back
  after the write). `deliveredInternally`: same-server colleagues. A quiet write
  that still mailed someone shows up in `warnings` — report it.
  Events that are entirely in the past are never mailed by the server.
""",
    "recurring": """\
RECURRING EVENTS

  --occurrence DATE   one occurrence (date, or date+time if several per day).
                      DATE is the day it happens now OR the day it was planned.
  --series            all occurrences. Moving a series shifts every occurrence;
                      already-changed occurrences keep their own times.

Changing one occurrence stores an "override" in the series. The tool writes it in
the SAME time form as the series (floating vs. time zone) — mixing the forms is
what makes Thunderbird show the original and the moved occurrence together.
Deleting one occurrence adds an exclusion (EXDATE) and drops its override.
""",
    "times": """\
TIMES

  Dates:     2026-11-06, 06.11.2026, 06.11., today, tomorrow, mon..sun (next), +3d
             German words work too: heute, morgen, montag..sonntag, fr
  Date-time: '2026-11-06 11:30', '2026-11-06T11:30', 'tomorrow 9:00', 'fri 14:00'
  Time only: '11:30' = that time on the event's (occurrence's) own day
  Durations: 30m, 1h30m, 2.5h, 1d, signed for shifts: +30m, -1h
  Zone:      the profile's (auth login --timezone; default this machine's).
             Output carries the UTC offset, e.g. 2026-11-06T11:30+01:00.
  Floating times (no zone, common in Exchange invites) are read in your zone.
""",
    "diagnose": """\
DIAGNOSE — the problems calendar apps do not show you

  occurrence-form-mismatch (error, fixable)
      The series is stored without a time zone, the changed occurrence with one
      (or the reverse). Thunderbird shows the original AND the moved occurrence.
  excluded-but-changed (error, fixable)
      The occurrence is excluded (EXDATE) and changed at the same time — typical
      after deleting the duplicate in Thunderbird. Thunderbird shows nothing,
      the web calendar shows the moved one.
  orphan-occurrence (warning)
      A changed occurrence that no longer matches the rule (series moved later).
  duplicate-uid (warning)
      The same event stored twice; delete one copy.

  `nextcloud-calendar diagnose` checks 30 days back to one year ahead
  (--all: everything; --event REF: one). --fix repairs quietly and re-checks.
  --exit-code makes findings exit 20 (for scripts); default is 0.
""",
    "import": """\
IMPORT — apply an invitation mail

  nextcloud-calendar event import FILE [--accept|--decline|--tentative] [--notify]

  FILE is an .ics attachment or a whole saved mail (.eml). REQUEST adds or
  updates (series updates keep your answer and alarms; occurrence updates are
  merged in the series' time form and un-exclude the occurrence). CANCEL marks
  the event / occurrence as cancelled. Stale updates (lower SEQUENCE) are
  skipped unless --force. Without --notify nobody is mailed.
""",
    "auth": """\
AUTH

  Browser (recommended for humans):
      nextcloud-calendar auth login --url https://cloud.example.com --web
      -> approve in the browser; a dedicated app password is created and
         stored in the OS keyring (never in a file, never in argv).
  Existing app password:
      printf %s "$PW" | nextcloud-calendar auth login --url URL --user NAME --token-stdin
  Headless (agents/CI):
      export NEXTCLOUDCALENDAR_URL=https://cloud.example.com
      export NEXTCLOUDCALENDAR_USER=alex
      export NEXTCLOUDCALENDAR_TOKEN=xxxxx-xxxxx       # an app password
      (also accepted: NEXTCLOUD_URL, NEXTCLOUD_USER, NEXTCLOUD_APP_PASSWORD).
      Env beats the keyring; `auth status` says which one spoke.
  Who am I in invitations? `nextcloud-calendar auth whoami` lists the addresses;
      add aliases with `auth login ... --address me@other-domain.de`.
  `nextcloud-calendar auth logout` deletes the local copy; revoke the app
      password in Nextcloud (Settings -> Security) as well.
""",
    "output": """\
OUTPUT

  JSON on stdout (default), -o table | markdown | csv for humans.
  --fields start,summary,id   project to these keys (dotted paths work).
  --stream                    NDJSON for `event list`.
  --dry-run                   print the first write request and exit 0 (reads still run).
  Write commands return: action, mode (quiet|notify), role, mailed[],
  deliveredInternally[], scheduling[] (raw SCHEDULE-STATUS per recipient),
  notes[], warnings[], and `event` (the affected occurrence as it is now).

  RESERVED (never a command's own option): --format/-f, --output/-o, --fields,
  --columns, --dry-run, --stream, --no-context. File outputs are `--out`.
""",
    "context": """\
STICKY CONTEXT — defaults that persist across commands

    nextcloud-calendar context set --calendar personal   # stop typing --calendar
    nextcloud-calendar context show                      # and WHICH profile it belongs to
    nextcloud-calendar context clear
    nextcloud-calendar --no-context event list           # ignore it for one command

  context is IMPLICIT state that changes command behaviour. If output looks wrongly
  scoped, run `context show` or add `--no-context`. Don't assume a fresh
  environment is context-free.

  Keys: calendar. It matches the real --calendar option (a test enforces that).
  Context is stored per profile and fills OPTIONS only, never an event reference.
  `auth`, `diagnose`, `trash`, `raw`, `settings`, `guide`, `install` and `context`
  itself ignore it on purpose: they are what you run when something looks wrong.
""",
    "settings": """\
SETTINGS

    nextcloud-calendar settings show
    nextcloud-calendar settings set-format table     # default output format
    nextcloud-calendar settings path                 # where the config file lives

  Default format is json (asked once on a TTY). Per-profile values (address,
  user, time zone, default calendar) are written by `auth login`.

  The config file holds NO secrets. App passwords live in the OS keyring (or a
  0600 file if no keyring is available).

  RELOCATE EVERYTHING
    export NEXTCLOUDCALENDAR_CONFIG_DIR=/some/path   # config + fallback credentials
""",
    "gotchas": """\
GOTCHAS

  - Recurring + neither --occurrence nor --series -> exit 7 by design.
  - Exit 6 = the event changed on the server between read and write (someone
    synced). Nothing was written; just run the command again.
  - Exit 8 = the notify/quiet wish cannot be honoured; the message says what can.
  - An attendee's move/extend only changes your own copy. The organizer's next
    update mail would overwrite it if you import it (that is correct behaviour).
  - Quiet attendee writes switch server replies off for that event
    (SCHEDULE-AGENT=CLIENT). `event respond --notify` still works afterwards.
  - Read-only shared calendars refuse writes (exit 4).
  - Thunderbird only shows changes after it syncs the calendar.
  - Titles are matched as substrings across ALL calendars, 31 days back to
    ~13 months ahead; use ids for anything else.
""",
}


def guide(topic: str = typer.Argument(None, help="A topic to expand; omit for the overview.")) -> None:
    """Built-in operating guide — how to use this CLI without external docs."""
    if topic is None:
        typer.echo(OVERVIEW)
        return
    key = topic.strip().lower()
    if key in ("topics", "list"):
        typer.echo("\n".join(sorted(TOPICS)))
        return
    body = TOPICS.get(key)
    if body is None:
        # Never a bare "unknown topic": this command is the way out of not knowing.
        typer.echo(f"No topic {topic!r}. Available:\n  " + "  ".join(sorted(TOPICS)) + "\n\nRun `nextcloud-calendar guide` for the overview.", err=True)
        raise typer.Exit(2)
    typer.echo(body)
