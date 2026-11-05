# Live findings: Nextcloud 35.0.2 CalDAV scheduling

Observed on 2026-11-05 against `nextcloud:35.0.2-apache` (the production major)
with Mailpit catching every iMIP mail. Scripts: `s1_scheduling.py` to
`s4_reply_trash.py`, verbatim output in the matching `.out` files. Every rule the
CLI relies on is listed here with the scenario that showed it. Where reasoning
and observation disagreed, observation won (see "Surprises").

Setup: users `alex` and `bob` on the server, `carol@external.test` and
`organizer@external.test` outside.

## Attendee side (someone else organises)

| Scenario | Write | Mail sent |
|---|---|---|
| A1, G0, D7 | create object with my PARTSTAT=ACCEPTED/TENTATIVE | REPLY to organizer |
| D1 | create with PARTSTAT=NEEDS-ACTION | none |
| A2, A3, D5 | change DTSTART/DTEND (move, extend) | none, ever |
| A5, D2, D3, R1c, R3b | change PARTSTAT, stored copy has no LAST-MODIFIED | none |
| D4, R2b-d, R3c-d, R5b-c | change PARTSTAT, stored copy has LAST-MODIFIED | REPLY |
| G1 | add an override (series) | REPLY |
| G2 | add an EXDATE (series) | REPLY |
| D6, D8 | DELETE an accepted event | REPLY (decline) |
| A8 | DELETE with `Schedule-Reply: F` | none |
| A9-A11, R1a, R6c | anything while ORGANIZER has `SCHEDULE-AGENT=CLIENT` | none |
| R6b | strip CLIENT + change PARTSTAT + bump LAST-MODIFIED | REPLY |
| R4a | create, event entirely in the past | none |

Why LAST-MODIFIED matters: Sabre's REPLY message carries only UID, SEQUENCE,
RECURRENCE-ID, ORGANIZER, ATTENDEE. Nextcloud's `EventComparisonService` drops a
message whose (RECURRENCE-ID, RRULE, SEQUENCE, LAST-MODIFIED) tuple equals the
stored component's. So a stored copy without LAST-MODIFIED and RRULE looks
"unchanged" and the REPLY is swallowed (log: "iTip message said the change was
significant but comparison did not detect any updated VEvents").

Thunderbird stores invites it received by e-mail with
`ORGANIZER;SCHEDULE-AGENT=CLIENT`. The 2026-11-05 repair of a real series
therefore sent nothing (confirmed by replay F1-F3).

## Organizer side (I organise, others attend)

| Scenario | Write | Mail sent | Internal attendee (bob) |
|---|---|---|---|
| B1, H0 | create with attendees | REQUEST to all | copy delivered |
| B2, E3 | move, SEQUENCE and LAST-MODIFIED unchanged | none | copy updated |
| E4 | move, SEQUENCE +1 | REQUEST to all | copy updated |
| H3 | LAST-MODIFIED changed only | REQUEST to all | copy updated |
| H1 | add an override (one occurrence changed) | REQUEST to all | copy updated |
| H2 | add EXDATE, SEQUENCE unchanged | none | EXDATE applied |
| E5 | STATUS:CANCELLED + SEQUENCE +1 | CANCEL to all (incl. organizer as attendee) | cancelled |
| B4 | DELETE | CANCEL to all except organizer | cancelled |
| E6 | DELETE with `Schedule-Reply: F` | none | copy stays |
| B5-B7 | anything with ATTENDEE;SCHEDULE-AGENT=CLIENT | none | nothing delivered |
| H4 | add CLIENT to attendees of an existing event | none | **copy set CANCELLED** |
| E2, H5 | remove CLIENT again, nothing else changed | none | copy re-delivered |

Consequence for the CLI: a quiet organizer edit keeps SEQUENCE and
LAST-MODIFIED. Changing a single occurrence of an own series cannot be quiet
(H1), and the CLIENT trick is harmful (H4), so the CLI refuses with exit 8.

## Server behaviour worth knowing

- PUT often returns no ETag (whenever scheduling rewrote the object). Re-read.
- After delivery the server writes `SCHEDULE-STATUS` on ORGANIZER/ATTENDEE:
  `1.1` mailed, `1.0` not significant, `1.2`/`2.0` delivered internally. The CLI
  strips it before a write and reads it back after, to report what happened.
- `If-None-Match: *` on an existing name: 412. Stale `If-Match`: 412.
- A second object with an existing UID in the same calendar: 409.
- Server-side `<c:expand>` treats floating times as UTC (F1-F3). The CLI expands
  occurrences itself and reads floating times in the user's zone.
- Trash: `REPORT calendar-query` on `/calendars/<u>/trashbin/objects/` lists
  deleted objects (PROPFIND Depth 1 is 501). Restore: `MOVE` to
  `/trashbin/restore/<id>`. Permanent delete: `DELETE` on the trash item.
- Trash name clash: deleting `X.ics` while an older `X.ics` of a different UID
  sits in the trash fails with 403 "... can't be moved into the trashbin".
  Re-creating with the same UID silently replaces the old trash entry instead.

## The 2026-11-05 incident, replayed (s2 F1-F3)

| State | Server expansion for that Friday | Thunderbird |
|---|---|---|
| As left by Thunderbird: floating series, override with Windows TZID, EXDATE for the occurrence | override only | nothing |
| EXDATE removed | override + original (duplicate) | duplicate |
| override rewritten floating | override only | correct |

recurring-ical-events (Python) shows one occurrence in the middle state: clients
disagree, which is exactly why `diagnose` checks the stored forms instead of
trusting any one client's expansion.

## Surprises (reasoning that was wrong)

- "Declining sends a REPLY": only if the stored copy carries LAST-MODIFIED (or RRULE).
- "A move without SEQUENCE bump is invisible to others": internal attendees get
  their copy moved anyway.
- "SCHEDULE-AGENT=CLIENT is a harmless mute switch": on the organizer side it
  cancels the event in internal attendees' calendars.
- "Deleting puts it in the trash": not if the trash already holds the name.
