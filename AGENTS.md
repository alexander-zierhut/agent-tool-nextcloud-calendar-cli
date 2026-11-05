# Using `nextcloud-calendar` from an AI agent

The **machine contract** for driving this CLI. For the human tutorial see the
[README](README.md); for every option see [docs/COMMANDS.md](docs/COMMANDS.md).
Changing the tool itself? See [BUILDING.md](BUILDING.md).

> **No context? Start here:** run **`nextcloud-calendar guide`**. The CLI ships its own
> playbook (output contract, auth, the domain model, verified gotchas) so you can
> bootstrap from the binary alone, with no external docs and no network. Then
> `nextcloud-calendar guide <topic>`.

## The output contract

- **stdout is JSON.** Parse it. Success exits `0`.
- **Errors are JSON on stderr**, non-zero exit: `{"error": "...", "detail": {...}}`.
- There is no non-JSON output (`event get --ics` returns the raw iCalendar
  inside a JSON field).
- **Exit codes** are stable, published API; branch on them:

  | Code | Meaning |
  | --- | --- |
  | 0 | success (including a successful `--dry-run`, and `diagnose` with findings) |
  | 1 | generic error |
  | 3 | config (no profile / bad config) |
  | 4 | auth (401/403: app password missing or wrong, or a read-only calendar) |
  | 5 | not found (404) |
  | 6 | conflict: the event changed on the server between read and write (412/409). Nothing was written; re-run |
  | 7 | validation: bad input, or an ambiguous reference (the candidates are listed) |
  | 8 | scheduling refused: the quiet/notify wish cannot be honoured exactly; the message says what can |
  | 20 | `diagnose --exit-code` found something (without `--exit-code`, findings exit 0) |
  | 130 | interrupted (SIGINT) |

  `2` is Click/Typer usage error, never allocated. Codes `0-7` mean the same
  across the whole tool family; `8` and `20` are this tool's own.

## Run it non-interactively

```bash
export NEXTCLOUDCALENDAR_URL=https://cloud.example.com
export NEXTCLOUDCALENDAR_USER=alex
export NEXTCLOUDCALENDAR_TOKEN=xxxxx-xxxxx-xxxxx-xxxxx-xxxxx   # an app password
nextcloud-calendar event list
```

`NEXTCLOUD_URL`, `NEXTCLOUD_USER` and `NEXTCLOUD_APP_PASSWORD` are accepted too.
The env token wins over the keyring. The CLI never prompts unless **stdin and
stdout are both TTYs**, so a pipeline can never be blocked by a question.

## The premise: quiet by default, verified after every write

Nextcloud does server-side scheduling: a change to an event with attendees can
make the server e-mail other people. Every write here changes only the user's
calendar unless `--notify` is passed, and every write returns `mailed`: the
recipients the server itself recorded as mailed (`SCHEDULE-STATUS`, read back
after the write), not a prediction. Report it to the user.

```bash
nextcloud-calendar event move "Weekly" --occurrence 2026-11-06 --to 11:30
nextcloud-calendar event update ID --duration 2h30m
nextcloud-calendar event respond ID declined --notify   # tells the organizer
```

Read `nextcloud-calendar guide scheduling` before using `--notify`.

## Spend fewer tokens

- **`--fields`** trims the payload: `--fields start,summary,id`.
- **`--stream`** emits NDJSON, one object per line (`event list`).
- **`-o csv` / `-o table` / `-o markdown`** when JSON isn't the right shape.

These **globals** work **anywhere on the line**, before or after the subcommand:
`--output`/`-o`, `--format`/`-f`, `--fields`/`--columns`, `--dry-run`, `--stream`
and `--no-context`. They're stripped from argv before parsing, so no command may
declare one of those names as its own option.

## Preview writes

Add **`--dry-run`** to any mutating command. It is intercepted in the transport, so
every write gets it and none can bypass it.

```bash
nextcloud-calendar event create --title "Review" --start "fri 14:00" --duration 45m --dry-run
# -> {"dryRun": true, "request": {"method": "PUT", "url": "...", ...}}
```

## Gotchas worth knowing

- **Recurring events need `--occurrence DATE` or `--series`.** Neither is assumed (exit 7).
- **Refer to events by `id`** (calendar/file.ics) from `event list`. Titles work
  but are refused when ambiguous.
- **"Cancel" depends on the role** (`role` is in every row): organizer ->
  `event cancel`; attendee -> `event respond ID declined`.
- **An attendee cannot send a new time to the organizer** (iTIP has no way);
  `event move` then changes only the user's own copy.
- **context is IMPLICIT state that changes command behaviour. If output looks
  wrongly scoped, run `context show` or add `--no-context`. Don't assume a fresh
  environment is context-free.**
- **Thunderbird caches:** changes appear there after its next sync.

Use `--profile/-p <name>` to target a specific Nextcloud login when several are
configured (`nextcloud-calendar auth profiles`).

## Reporting a problem — open a GitHub issue

If a task was painful, needed too many steps, hit a missing feature, or was
impossible with `nextcloud-calendar` — **and the user asks you to file it** — open an issue on
this tool's own repo. Only when asked; never unprompted; one issue per problem.

- Repo: `alexander-zierhut/agent-tool-nextcloud-calendar-cli`
- Issues: https://github.com/alexander-zierhut/agent-tool-nextcloud-calendar-cli/issues
- Self-contained (no repo/README needed beside the binary): `nextcloud-calendar report` prints exactly this — the repo, a pre-filled `issues/new` link, and a `gh` one-liner — offline, no token.

Search for a duplicate first, then file — prefer the `gh` CLI:

```bash
gh issue list   --repo alexander-zierhut/agent-tool-nextcloud-calendar-cli --search "<keywords>"
gh issue create --repo alexander-zierhut/agent-tool-nextcloud-calendar-cli \
  --title "<one-line summary>" \
  --body  "<goal · exact command(s) run · JSON error + exit code · `nextcloud-calendar --version` · what would have made it work>"
```

If `gh` is missing or unauthenticated, hand the user a prefilled link instead:
`https://github.com/alexander-zierhut/agent-tool-nextcloud-calendar-cli/issues/new?title=…&body=…`.
