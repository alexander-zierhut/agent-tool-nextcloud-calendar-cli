# nextcloud-calendar — the agent-ready Nextcloud calendar CLI

> Move, lengthen, cancel and answer **Nextcloud calendar** appointments, including
> meetings someone else organised, **without e-mailing anyone unless you say so**,
> and repair recurring meetings that Thunderbird shows twice or not at all. Built
> to be driven by **AI agents** (Claude, Cursor, LLM tool-loops) as well as humans.

[![PyPI](https://img.shields.io/pypi/v/agent-tool-nextcloud-calendar-cli)](https://pypi.org/project/agent-tool-nextcloud-calendar-cli/)
[![CI](https://github.com/alexander-zierhut/agent-tool-nextcloud-calendar-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/alexander-zierhut/agent-tool-nextcloud-calendar-cli/actions/workflows/ci.yml)
![Python](https://img.shields.io/pypi/pyversions/agent-tool-nextcloud-calendar-cli)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Agent ready](https://img.shields.io/badge/agent-ready-8A2BE2)

**Install:** `pipx install agent-tool-nextcloud-calendar-cli` — then run `nextcloud-calendar guide`.

[**agent-tool-nextcloud-calendar-cli**](https://pypi.org/project/agent-tool-nextcloud-calendar-cli/)
(the installed command is `nextcloud-calendar`) is a Python command-line interface
for [Nextcloud](https://nextcloud.com/) calendars over CalDAV. It edits the events
on the server, the same data Thunderbird, phones and the web calendar show, and it
does the things calendar apps refuse to do:

- move, lengthen or cancel a meeting someone else organised, in your own
  calendar, without e-mailing anyone
- answer invitations with or without telling the organizer, and prove which it was
- find and repair recurring meetings that show an occurrence twice or not at all
- apply an invitation mail (.ics or .eml) without the Thunderbird glitches
- restore deleted events from Nextcloud's calendar trash

**Keywords:** Nextcloud calendar CLI, CalDAV command line, Nextcloud CalDAV client,
iCalendar, iTIP scheduling, Thunderbird, recurring events, appointments, calendar
automation, AI agent tool, LLM tooling, Claude.

## Quiet by default, verified after every write

Nextcloud does server-side scheduling: a change to an event with attendees can
make the server mail other people. Which changes do that was measured against
Nextcloud 35 with a mail catcher (see [spike/FINDINGS.md](spike/FINDINGS.md)).
The CLI writes so that nobody is mailed unless you pass `--notify`, and every
write reports `mailed`: the recipients the server itself recorded as mailed
(`SCHEDULE-STATUS` read back after the write), not a prediction.

| You are | Quiet (default) | `--notify` |
|---|---|---|
| attendee | your copy only; server replies switched off for the event (as Thunderbird does for mailed invites) | `event respond` mails your answer; a new time cannot be sent (exit 8) |
| organizer | SEQUENCE/LAST-MODIFIED kept, no mail; colleagues on the same server see the change | update or cancellation mailed to all |

Changing one occurrence of a series you organise always mails everyone on
Nextcloud, so the quiet version is refused (exit 8) instead of guessed.

## The command surface

Everything is discoverable from the binary: `nextcloud-calendar --help`, then
`nextcloud-calendar guide` for the playbook and `nextcloud-calendar <group> --help`
for any group. The top level:

```text

 Usage: nextcloud-calendar [OPTIONS] COMMAND [ARGS]...

 Agent-friendly CLI for Nextcloud calendars (CalDAV): list, move, extend, cancel
 and answer appointments, and repair recurring meetings that show twice or
 vanished. Quiet by default: nobody is e-mailed unless you pass --notify.

 Output is JSON on stdout by default (errors are JSON on stderr with a non-zero
 exit code); add `-o table` or trim with `--fields`.

 New here / no context? Run `nextcloud-calendar guide` for the full playbook.

╭─ Options ────────────────────────────────────────────────────────────────────────╮
│ --output            -o      <json|table|markdown|csv>  json (default), table,    │
│                                                        markdown, csv. Also       │
│                                                        --format/-f, anywhere on  │
│                                                        the line.                 │
│ --fields,--columns          <str>                      Comma-separated fields,   │
│                                                        e.g. 'start,summary,id'.  │
│                                                        Anywhere on the line.     │
│ --profile           -p      <str>                      Configuration profile.    │
│ --dry-run                                              Writes: print the request │
│                                                        that would be sent and    │
│                                                        exit 0.                   │
│ --stream                                               Stream list results as    │
│                                                        NDJSON.                   │
│ --no-context                                           Ignore the saved session  │
│                                                        context for this command. │
│ --no-color                                             Disable coloured output.  │
│ --version           -V                                 Show version and exit.    │
│ --help                                                 Show this message and     │
│                                                        exit.                     │
╰──────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────╮
│ guide     Built-in operating guide — how to use this CLI without external docs.  │
│ report    Report a bug or missing feature — prints this tool's repo and a        │
│           pre-filled issue link (offline, no token).                             │
│ diagnose  Find (and --fix) recurring events that show twice or vanished in some  │
│           clients.                                                               │
│ event     Events: list, get, create, move, update, respond, cancel, delete,      │
│           import.                                                                │
│ calendar  Your calendars and their ids.                                          │
│ trash     Deleted events: list, restore, purge.                                  │
│ auth      Log in (browser flow or app password), status, whoami, log out.        │
│ raw       Escape hatch: any WebDAV/CalDAV request.                               │
│ settings  View & change CLI settings.                                            │
│ context   Sticky session defaults (e.g. a default --calendar), per profile.      │
│ install   Integrate with other tools (e.g. `install claude`).                    │
╰──────────────────────────────────────────────────────────────────────────────────╯

 Learn more:  `nextcloud-calendar guide`  ·  `nextcloud-calendar guide scheduling`

```

Global options (`-o`, `--fields`, `--dry-run`, `--stream`, `--no-context`) work
anywhere on the line. Full reference: [docs/COMMANDS.md](docs/COMMANDS.md).

## Quick start

```bash
nextcloud-calendar auth login --url https://cloud.example.com --web   # browser approval, app password -> OS keyring
nextcloud-calendar event list --from mon --days 5 -o table
nextcloud-calendar event move "Weekly" --occurrence 2026-11-06 --to 11:30
nextcloud-calendar event update "Workshop" --duration 2h30m
nextcloud-calendar event respond "Jour fixe" declined --notify
nextcloud-calendar diagnose --fix
nextcloud-calendar install claude    # register the Claude Code skill
```

Agents and CI use environment variables instead of a login:
`NEXTCLOUDCALENDAR_URL`, `NEXTCLOUDCALENDAR_USER`, `NEXTCLOUDCALENDAR_TOKEN` (an
app password), optionally `NEXTCLOUDCALENDAR_TIMEZONE` and
`NEXTCLOUDCALENDAR_ADDRESSES`. `NEXTCLOUD_URL`, `NEXTCLOUD_USER` and
`NEXTCLOUD_APP_PASSWORD` work too.

## Output for agents

- Default output is JSON on **stdout**. Errors are JSON on **stderr** with a
  non-zero exit code.
- Exit codes follow the family contract: `0` ok · `1` generic · `3` config ·
  `4` auth · `5` not-found · `6` conflict (changed on the server meanwhile, re-run) ·
  `7` validation or ambiguous reference (candidates listed) · `8` scheduling refused ·
  `20` findings with `diagnose --exit-code` · `130` interrupted.

Full contract: [AGENTS.md](AGENTS.md).

## Known limitations (Nextcloud and iTIP, not the CLI)

- An attendee cannot propose a new time to the organizer through the server;
  `event move` on someone else's meeting changes your copy only.
- Changing one occurrence of a series you organise always mails every attendee
  on Nextcloud (the CLI refuses the quiet variant with exit 8).
- Events entirely in the past are never mailed by the server, even with `--notify`.
- Deleting an event fails with 403 when the trash already holds an object with the
  same file name; `trash purge` clears it.

## The name

The command is `nextcloud-calendar`, not `nextcloud` (the desktop sync client's
binary) and not `ncal` (the BSD calendar tool), so it never shadows something
already on your PATH.

## Contributing / Development

**You do not need a Nextcloud account to contribute.** Clone it and run:

```bash
pip install -e '.[test]'
pytest                 # hermetic tests are green on a clean checkout, no server
```

The integration tests drive the real binary against a throwaway Nextcloud 35 with
Mailpit catching every mail the server sends, and assert the mailbox:

```bash
make up                # Nextcloud 35 + Mailpit in Docker, seeded (users alex, bob)
make test-integration
make down
```

They refuse any server that is not on loopback. See [BUILDING.md](BUILDING.md)
for the rules every write follows.

## Part of the family

Built on **[agent-tool-shared-cli](https://github.com/alexander-zierhut/agent-tool-shared-cli)** —
the chassis every tool in this family shares: JSON on stdout, JSON errors on
stderr, a stable cross-tool exit-code contract, `--dry-run`, four output formats,
and a built-in `guide` so an agent can learn each tool from the tool itself.

| Tool | Install | For |
| --- | --- | --- |
| [**drone-cli**](https://github.com/alexander-zierhut/agent-tool-drone-cli) | `pipx install agent-tool-drone-cli` | Drone CI — builds, failing-step logs, promotions |
| [**grafana-cli**](https://github.com/alexander-zierhut/agent-tool-grafana-cli) | `pipx install agent-tool-grafana-cli` | Grafana — log discovery, health scan, alert routing |
| [**openproject**](https://github.com/alexander-zierhut/agent-tool-openproject-cli) | `pipx install agent-tool-openproject-cli` | OpenProject — work packages, time, invoicing |
| [**lexware-office**](https://github.com/alexander-zierhut/agent-tool-lexware-office-cli) | `pipx install agent-tool-lexware-office-cli` | Lexware Office — invoices, contacts, AR-aging |
| [**close**](https://github.com/alexander-zierhut/agent-tool-close-crm-cli) | `pipx install agent-tool-close-crm-cli` | Close CRM — leads, contacts, tasks, opportunities |
| [**readmd**](https://github.com/alexander-zierhut/agent-tool-readmd-cli) | `pipx install agent-tool-readmd-cli` | Text-to-speech — read text aloud with a read-along window |
| [**nextcloud-calendar**](https://github.com/alexander-zierhut/agent-tool-nextcloud-calendar-cli) | `pipx install agent-tool-nextcloud-calendar-cli` | Nextcloud calendar — move, extend, cancel, answer, repair recurring events |

They compose over the shared contract:
`nextcloud-calendar event list --from mon --days 5 --fields start,summary -o csv | readmd read -`
reads your week aloud.

## License

MIT — see [LICENSE](LICENSE).
