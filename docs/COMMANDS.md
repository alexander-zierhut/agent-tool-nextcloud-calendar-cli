# Command reference

_Auto-generated from the CLI (`python scripts/gen_docs.py`)._

_Every command also accepts `--output/-o` (json\|table\|markdown\|csv), `--format/-f`, `--fields`/`--columns`, `--dry-run`, `--stream` and `--no-context`. Those are **stripped from argv before parsing**, so they work anywhere on the line — before or after the subcommand. `--profile/-p` and `--no-color` are ordinary root options and must therefore come **before** the subcommand (`nextcloud-calendar -p work event list`, not `nextcloud-calendar event list -p work`)._

## Groups

- [`auth`](#auth) — Log in (browser flow or app password), status, whoami, log out.
- [`calendar`](#calendar) — Your calendars and their ids.
- [`context`](#context) — Sticky session defaults (e.g. a default --calendar), per profile.
- [`diagnose`](#diagnose) — Find (and --fix) recurring events that show twice or vanished in some clients.
- [`event`](#event) — Events: list, get, create, move, update, respond, cancel, delete, import.
- [`guide`](#guide) — Built-in operating guide — how to use this CLI without external docs.
- [`install`](#install) — Integrate with other tools (e.g. `install claude`).
- [`raw`](#raw) — Escape hatch: any WebDAV/CalDAV request.
- [`report`](#report) — Report a bug or missing feature — prints this tool's repo and a pre-filled issue link (offline, no token).
- [`settings`](#settings) — View & change CLI settings.
- [`trash`](#trash) — Deleted events: list, restore, purge.

## `auth`

### `nextcloud-calendar auth login`

Log in and store the app password in the OS keyring.

Example: `nextcloud-calendar auth login --url https://cloud.example.com --web`
opens the browser; approve there. With an existing app password:
`printf %s "$PW" | nextcloud-calendar auth login --url ... --user alex --token-stdin`.
The login is verified BEFORE anything is saved. Headless agents skip this and
set NEXTCLOUDCALENDAR_URL, _USER and _TOKEN instead.

| Option | Description |
| --- | --- |
| `--url` | Your Nextcloud address, e.g. https://cloud.example.com (env: NEXTCLOUDCALENDAR_URL). |
| `--user` | Login name (env: NEXTCLOUDCALENDAR_USER). Not needed with the browser flow. |
| `--token` | An existing app password. Prefer --token-stdin (keeps it out of argv) or the browser flow. |
| `--token-stdin` | Read an existing app password from stdin (keeps it out of argv and shell history). |
| `--web` | Browser login flow even without a terminal (prints the URL, waits for approval). |
| `--address` | Extra e-mail address that means 'me' in invitations (repeatable). |
| `--timezone` | IANA zone for floating times and output (default: this machine's). |
| `--profile` | Profile to write (default: the active one). |
| `--insecure` | Skip TLS verification (self-signed test servers only). |

### `nextcloud-calendar auth logout`

Delete the stored app password (revoke it in Nextcloud too: Settings -> Security).

The profile's address and settings stay; `auth login --profile <name>` re-adds
just the password.

| Option | Description |
| --- | --- |
| `--profile` | Profile to log out (default: the active one). |

### `nextcloud-calendar auth profiles`

List every configured profile and which one is active.

### `nextcloud-calendar auth status`

Which login/backend is in use, and whether the server accepts it. Never fails.

### `nextcloud-calendar auth whoami`

The logged-in principal: display name, e-mail addresses, default calendar.

## `calendar`

### `nextcloud-calendar calendar list`

List your calendars (own and shared with you) that hold events.

Example: `nextcloud-calendar calendar list`
Use the `id` with --calendar. `writable: false` = shared to you read-only.

## `context`

### `nextcloud-calendar context clear`

Remove every sticky default for the active profile.

### `nextcloud-calendar context set`

Set sticky defaults, e.g. `context set --calendar work`.

| Option | Description |
| --- | --- |
| `--calendar` | Default --calendar for every command. |

### `nextcloud-calendar context show`

Print the active context, whether it applies, and where it is stored.

## `diagnose`

### `nextcloud-calendar diagnose`

Find (and --fix) recurring events that show twice or vanished in some clients.

| Option | Description |
| --- | --- |
| `--event` | Check just this event (id, UID or title). |
| `--calendar` | Calendar id or name (see `calendar list`). Default: all calendars for lookups, your default calendar for new events. |
| `--all` | Check every stored event, not just those from 30 days ago to a year ahead. |
| `--fix` | Repair what is repairable, quietly (nobody is mailed). |
| `--exit-code` | Exit 20 when there are findings (default: findings exit 0). |

## `event`

### `nextcloud-calendar event cancel`

Mark an event (or one occurrence) as cancelled; it stays visible, struck through.

Example: `nextcloud-calendar event cancel "Team-Lunch" --occurrence fri`
Use `event delete` to remove it instead, `event respond ... declined` to
say you will not attend someone else's meeting.

**Arguments:** `ref` (required)

| Option | Description |
| --- | --- |
| `--occurrence` | Which occurrence of a recurring event: a date (2026-11-06, 06.11.2026, fri, tomorrow) or date+time. |
| `--series` | Apply to every occurrence of a recurring event. |
| `--calendar` | Calendar id or name (see `calendar list`). Default: all calendars for lookups, your default calendar for new events. |
| `--notify` | You organise it: mail the cancellation to every attendee. |

### `nextcloud-calendar event create`

Create an event in your default (or the given) calendar.

Example: `nextcloud-calendar event create --title "Zahnarzt" --start "2026-11-12 08:30" --duration 45m`
With --attendee but without --notify the people are recorded, not invited.

| Option | Description |
| --- | --- |
| `--title` | What it is. **(required)** |
| `--start` | '2026-11-06 11:30', 'tomorrow 9:00', 'fri 14:00', or a date for all-day. **(required)** |
| `--end` | End time or date-time (default: start + --duration). |
| `--duration` | e.g. 30m, 1h30m, 2.5h (default 1h; all-day: 1d). |
| `--calendar` | Calendar id or name (see `calendar list`). Default: all calendars for lookups, your default calendar for new events. |
| `--location` |  |
| `--description` |  |
| `--attendee` | E-mail of someone to invite (repeatable). Invited only with --notify. |
| `--notify` | Send invitations to the --attendee addresses. |

### `nextcloud-calendar event delete`

Delete an event, or remove one occurrence from a series.

Example: `nextcloud-calendar event delete "Zahnarzt"`
Deleted events go to the trash (`trash list` / `trash restore`).

**Arguments:** `ref` (required)

| Option | Description |
| --- | --- |
| `--occurrence` | Which occurrence of a recurring event: a date (2026-11-06, 06.11.2026, fri, tomorrow) or date+time. |
| `--series` | Apply to every occurrence of a recurring event. |
| `--calendar` | Calendar id or name (see `calendar list`). Default: all calendars for lookups, your default calendar for new events. |
| `--notify` | Organizer: mail a cancellation. Attendee: decline to the organizer first. |

### `nextcloud-calendar event get`

Show one event: times, series rule, changed/excluded occurrences, people.

Example: `nextcloud-calendar event get "Team Weekly"`
`serverScheduling: off` means the server never mails anyone about it
(typical for invites Thunderbird received by e-mail).

**Arguments:** `ref` (required)

| Option | Description |
| --- | --- |
| `--calendar` | Calendar id or name (see `calendar list`). Default: all calendars for lookups, your default calendar for new events. |
| `--ics` | Return the raw iCalendar text instead. |
| `--upcoming` | How many next occurrences to include. |

### `nextcloud-calendar event import`

Apply an invitation or update from an e-mail to your calendar — without the Thunderbird glitches.

Example: `nextcloud-calendar event import ~/Downloads/invite.eml --accept`
Updates for one occurrence are merged into the stored series in its own time
form, so the original and the moved occurrence never both show (and neither vanishes).

**Arguments:** `file` (required)

| Option | Description |
| --- | --- |
| `--calendar` | Calendar for NEW events (default: your default calendar). |
| `--accept` | Mark yourself as accepted. |
| `--decline` | Mark yourself as declined. |
| `--tentative` | Mark yourself as tentative. |
| `--force` | Apply even if the invitation is older than what is stored. |
| `--notify` | Send your answer to the organizer. |

### `nextcloud-calendar event list`

List occurrences in a time window, recurring events expanded, sorted by start.

Example: `nextcloud-calendar event list --from mon --days 5`
Each row's `id` (+ `occurrence` for recurring events) is what the other
commands take. Times are in your zone (`auth status` shows it).

| Option | Description |
| --- | --- |
| `--from` | First day (default: today). Accepts 2026-11-06, 06.11., today, mon, +3d. |
| `--to` | Last day, inclusive (default: --from + --days - 1). |
| `--days` | Window length when --to is not given. |
| `--calendar` | Calendar id or name (see `calendar list`). Default: all calendars for lookups, your default calendar for new events. |
| `--search` | Only events whose title/location/description contains this text. |
| `--limit` | At most this many occurrences. |

### `nextcloud-calendar event move`

Move an event (or one occurrence, or a whole series), keeping its length.

Example: `nextcloud-calendar event move "Team Weekly" --occurrence 2026-11-06 --to 11:30`
Quiet by default. For a meeting someone else organises this only changes
YOUR calendar — the server cannot propose a new time to the organizer.

**Arguments:** `ref` (required)

| Option | Description |
| --- | --- |
| `--to` | New start: '11:30' (same day), '2026-11-07 09:00', 'tomorrow 10:00'. Duration is kept. |
| `--by` | Shift by a duration: +30m, -1h, +1d. |
| `--occurrence` | Which occurrence of a recurring event: a date (2026-11-06, 06.11.2026, fri, tomorrow) or date+time. |
| `--series` | Apply to every occurrence of a recurring event. |
| `--calendar` | Calendar id or name (see `calendar list`). Default: all calendars for lookups, your default calendar for new events. |
| `--notify` | Let the server e-mail the other people on the event (organizer or attendees). Default is QUIET: only your calendar changes and nobody is mailed. |

### `nextcloud-calendar event respond`

Answer an invitation: accepted, declined or tentative.

Example: `nextcloud-calendar event respond "Jour fixe" declined --occurrence 2026-11-20 --notify`
Without --notify only your calendar records the answer.

**Arguments:** `ref` (required), `answer` (required)

| Option | Description |
| --- | --- |
| `--occurrence` | Which occurrence of a recurring event: a date (2026-11-06, 06.11.2026, fri, tomorrow) or date+time. |
| `--series` | Apply to every occurrence of a recurring event. |
| `--calendar` | Calendar id or name (see `calendar list`). Default: all calendars for lookups, your default calendar for new events. |
| `--notify` | Send your answer to the organizer (server e-mails a REPLY; verified). |

### `nextcloud-calendar event update`

Change times, length, title, location or description.

Example: `nextcloud-calendar event update "Workshop" --occurrence 2026-11-12 --duration 2h30m`
Quiet by default (only your calendar). --series changes every occurrence.

**Arguments:** `ref` (required)

| Option | Description |
| --- | --- |
| `--start` | New start (keeps the length unless --end/--duration given). |
| `--end` | New end: '13:30' (same day) or a full date-time. |
| `--duration` | New length, e.g. 2h30m. |
| `--extend` | Lengthen (or with '-', shorten) the end, e.g. +1h. |
| `--title` |  |
| `--location` |  |
| `--description` |  |
| `--occurrence` | Which occurrence of a recurring event: a date (2026-11-06, 06.11.2026, fri, tomorrow) or date+time. |
| `--series` | Apply to every occurrence of a recurring event. |
| `--calendar` | Calendar id or name (see `calendar list`). Default: all calendars for lookups, your default calendar for new events. |
| `--notify` | Let the server e-mail the other people on the event (organizer or attendees). Default is QUIET: only your calendar changes and nobody is mailed. |

## `guide`

### `nextcloud-calendar guide`

Built-in operating guide — how to use this CLI without external docs.

**Arguments:** `topic` (optional)

## `install`

### `nextcloud-calendar install claude`

Register `nextcloud-calendar` with Claude Code as a Skill. Reversible with --uninstall.

| Option | Description |
| --- | --- |
| `--project` | Install into ./.claude instead of ~/.claude. |
| `--memory` | Also add a one-line hint to ~/.claude/CLAUDE.md. |
| `--force` | Install even if Claude Code isn't detected. |
| `--uninstall` | Remove the skill (and memory hint). |
| `--print` | Print the SKILL.md that would be written and exit. |

## `raw`

### `nextcloud-calendar raw delete`

DELETE a resource. Without --no-schedule-reply the server may mail CANCEL/REPLY.

**Arguments:** `href` (required)

| Option | Description |
| --- | --- |
| `--if-match` |  |
| `--no-schedule-reply` | Send `Schedule-Reply: F` (no cancellation mails). |

### `nextcloud-calendar raw get`

GET a resource; returns its body and ETag. Example: `raw get /remote.php/dav/calendars/alex/personal/x.ics`.

**Arguments:** `href` (required)

### `nextcloud-calendar raw propfind`

PROPFIND with your own property list; parsed into JSON.

**Arguments:** `href` (required)

| Option | Description |
| --- | --- |
| `--props` | Inner <d:prop> XML (prefixes d c cs oc nc ical are declared). |
| `--depth` | 0, 1 (default) or infinity. |

### `nextcloud-calendar raw put`

PUT raw iCalendar. WARNING: bypasses the quiet-write rules — the server may e-mail attendees.

**Arguments:** `href` (required)

| Option | Description |
| --- | --- |
| `--file` | The .ics to upload. |
| `--data` | The body inline. |
| `--if-match` | Only overwrite this version (recommended). |

### `nextcloud-calendar raw report`

REPORT (calendar-query, sync-collection, ...); parsed into JSON.

**Arguments:** `href` (required)

| Option | Description |
| --- | --- |
| `--data` | The full REPORT XML body. |
| `--file` | Read the REPORT body from a file. |
| `--depth` |  |

## `report`

### `nextcloud-calendar report`

Report a bug or missing feature — prints this tool's repo and a pre-filled issue link (offline, no token).

## `settings`

### `nextcloud-calendar settings path`

Print the config file path.

### `nextcloud-calendar settings set-format`

Set the default output format.

**Arguments:** `fmt` (required)

### `nextcloud-calendar settings show`

Show every setting, its value, and where it came from.

## `trash`

### `nextcloud-calendar trash list`

List deleted events, newest first.

Example: `nextcloud-calendar trash list`
Deleting in Thunderbird, on a phone or with `event delete` all land here.

### `nextcloud-calendar trash purge`

Delete a trash entry for good (cannot be undone).

Example: `nextcloud-calendar trash purge 19.ics`
Needed only when Nextcloud refuses a delete because an older deleted copy
with the same name is in the trash (`event delete` handles that itself).

**Arguments:** `trash_id` (required)

### `nextcloud-calendar trash restore`

Put a deleted event back into its calendar. Sends no e-mail (observed).

Example: `nextcloud-calendar trash restore 19.ics`

**Arguments:** `trash_id` (required)

