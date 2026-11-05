# Building `agent-tool-nextcloud-calendar-cli`: notes for the next maintainer

Read `../_shared/BLUEPRINT.md`, `../_shared/BUILDING-THE-NEXT-CLI.md` and
`../_shared/SIMILARITY_CHECKLIST.md` first. This tool follows the family contract
(JSON stdout, exit codes, reserved global flags, `guide` offline, `install
claude`). [AGENTS.md](AGENTS.md) is the machine contract for agents that USE the
tool; this file is for people and agents that CHANGE it.

## The one rule for this tool

**A write must never mail someone the user did not intend to mail.** Every rule
in `src/nextcloudcalendar/scheduling.py` comes from an observation in
`spike/FINDINGS.md`. If you change how a write is built, add or update an
integration test that asserts the Mailpit inbox, and run it.

- Quiet attendee writes set `ORGANIZER;SCHEDULE-AGENT=CLIENT`.
- Quiet organizer writes keep SEQUENCE and LAST-MODIFIED byte-identical.
- Never put `SCHEDULE-AGENT=CLIENT` on attendees of an existing event (it cancels
  internal attendees' copies, FINDINGS H4).
- Strip `SCHEDULE-STATUS` before a PUT, read it back after, report it.
- When a wish cannot be honoured exactly, raise `SchedulingRefused` (exit 8) with
  the alternative in the message.

## Time forms

All comparisons of occurrence identities go through `ical.instant_key`, all
writes of date-times through `ical.write_dt` in the series' own form. Mixing
floating and zoned forms is the bug class `diagnose` exists for.

## Tests

- `pip install -e '.[test]' && pytest` is green with no Docker: the integration
  tier skips with a "run `make up`" reason.
- `make test-unit`: the hermetic tier, selected by marker (`-m "not integration"`).
- `make up && make test-integration`: Nextcloud 35 + Mailpit in Docker, seeded
  with users `alex` and `bob`. Dates in `tests/samples.py` are relative to today,
  because past events never mail. CI sets
  `NEXTCLOUDCALENDAR_REQUIRE_INTEGRATION=1`, so an unreachable stack fails
  instead of skipping silently.
- Write-safety interlock: the integration fixtures refuse any server that is not
  on loopback (`tests/test_interlock_unit.py` proves it). Never weaken that.
- Test data is synthetic (`example.test`, `external.test`). Real calendar data
  never goes into the repo; captured real responses belong in `spike/live/`
  (gitignored).

## Layout

`client.py` transport (Basic auth, conditional writes, Sabre error mapping,
retries, dry-run) · `dav.py` discovery, queries, trash · `ical.py` object model
and edit primitives · `scheduling.py` write rules · `diagnose.py` checks and
repairs · `itip.py` invitation import · `resolve.py` reference resolution ·
`serialize.py` output shapes · `commands/` thin CLI layer. The chassis
(`spec.py`, `errors.py`, `config.py`, `appctx.py`, `cli.py`, `commands/_shared.py`,
`auth`, `settings`, `context`, `install`, `report`, `raw`, `guide`) follows the
siblings; keep it aligned with them.

## Allowed differences from the family

- Exit `8` = scheduling refused (observed: Nextcloud mails everyone when one
  occurrence of an own series changes; there is no quiet way).
- Write interlock is "loopback only" instead of a `*_ALLOW_WRITES` flag: the test
  stack's credentials are synthetic, so a non-loopback URL can only be a mistake.
- The test backend is a real Nextcloud plus Mailpit, because what matters is
  which mails the server sends, and only a real server can answer that.
