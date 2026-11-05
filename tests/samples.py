"""Synthetic calendar objects shaped like what real clients store.

All data is invented (example.test / external.test). Dates are computed relative
to today, so the suite never rots into "the event is in the past" — where
Nextcloud deliberately stops mailing and every notify assertion would flip.
"""

from __future__ import annotations

import datetime as dt

ORG = "organizer@external.test"
ME = "alex@example.test"
BOB = "bob@example.test"
CAROL = "carol@external.test"

WIN_TZ = """BEGIN:VTIMEZONE
TZID:W. Europe Standard Time
BEGIN:STANDARD
DTSTART:16010101T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=10
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE
"""


def friday(weeks_ahead: int = 3) -> dt.date:
    """A Friday a few weeks from now (winter-time-safe for the fixed TZ above is not needed: we compare instants)."""
    d = dt.date.today() + dt.timedelta(weeks=weeks_ahead)
    return d + dt.timedelta(days=(4 - d.weekday()) % 7)


def stamp(d: dt.date, hh: int, mm: int = 0) -> str:
    return f"{d:%Y%m%d}T{hh:02d}{mm:02d}00"


def _people(organizer: str, attendees: list[str], *, org_params: str = "", my_status: str = "ACCEPTED", att_params: str = "") -> str:
    lines = [f"ORGANIZER;CN=Org{org_params}:mailto:{organizer}"]
    for a in attendees:
        st = my_status if a == ME else "NEEDS-ACTION"
        lines.append(f"ATTENDEE;CN={a.split('@')[0]};PARTSTAT={st};ROLE=REQ-PARTICIPANT;RSVP=TRUE{att_params}:mailto:{a}")
    return "\n".join(lines)


def wrap(*parts: str) -> str:
    return "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//tests//EN\n" + "".join(parts) + "END:VCALENDAR\n"


def vevent(uid: str, start: str, end: str, *, summary: str = "Weekly", tzid: str | None = None, rrule: str | None = None,
           exdates: list[str] = (), rid: str | None = None, rid_tzid: str | None = None, people: str = "",
           seq: int = 0, lastmod: bool = True, extra: str = "") -> str:
    tz = f";TZID={tzid}" if tzid else ""
    out = ["BEGIN:VEVENT", f"UID:{uid}", "DTSTAMP:20260101T000000Z", f"SUMMARY:{summary}", f"SEQUENCE:{seq}"]
    if lastmod:
        out.append("LAST-MODIFIED:20260101T000000Z")
    if rid:
        out.append(f"RECURRENCE-ID{';TZID=' + rid_tzid if rid_tzid else ''}:{rid}")
    out += [f"DTSTART{tz}:{start}", f"DTEND{tz}:{end}"]
    if rrule:
        out.append(f"RRULE:{rrule}")
    for x in exdates:
        out.append(f"EXDATE{tz}:{x}")
    if people:
        out.append(people)
    if extra:
        out.append(extra.rstrip("\n"))
    out.append("END:VEVENT")
    return "\n".join(out) + "\n"


def personal(uid: str = "personal-1", day: dt.date | None = None, hh: int = 9) -> str:
    d = day or friday()
    return wrap(vevent(uid, stamp(d, hh), stamp(d, hh + 1), summary="Dentist", tzid="Europe/Berlin"))


def invite_series(uid: str = "series-1", *, client: bool = True, floating: bool = True, lastmod: bool = True,
                  my_status: str = "ACCEPTED", count: int = 8) -> str:
    """An external organizer's weekly series, as Thunderbird stores an e-mailed invite
    (floating times, ORGANIZER;SCHEDULE-AGENT=CLIENT)."""
    d = friday()
    people = _people(ORG, [ME, CAROL], org_params=";SCHEDULE-AGENT=CLIENT" if client else "", my_status=my_status)
    return wrap(vevent(uid, stamp(d, 11), stamp(d, 11, 25), tzid=None if floating else "Europe/Berlin",
                       rrule=f"FREQ=WEEKLY;COUNT={count}", people=people, lastmod=lastmod))


def invite_single(uid: str = "single-1", *, client: bool = False, lastmod: bool = True, my_status: str = "ACCEPTED") -> str:
    d = friday()
    people = _people(ORG, [ME, CAROL], org_params=";SCHEDULE-AGENT=CLIENT" if client else "", my_status=my_status)
    return wrap(vevent(uid, stamp(d, 14), stamp(d, 15, 30), summary="Workshop", tzid="Europe/Berlin", people=people, lastmod=lastmod))


def own_series(uid: str = "own-1", count: int = 6) -> str:
    """A series alex organises with an internal (bob) and an external (carol) attendee."""
    d = friday() + dt.timedelta(days=-2)  # a Wednesday
    people = _people(ME, [ME, BOB, CAROL])
    return wrap(vevent(uid, stamp(d, 10), stamp(d, 11), summary="Jour fixe", tzid="Europe/Berlin",
                       rrule=f"FREQ=WEEKLY;COUNT={count}", people=people))


def own_single(uid: str = "own-single-1") -> str:
    d = friday() + dt.timedelta(days=-1)
    people = _people(ME, [ME, BOB, CAROL])
    return wrap(vevent(uid, stamp(d, 10), stamp(d, 11), summary="Kickoff", tzid="Europe/Berlin", people=people))


def broken_incident(uid: str = "incident-1") -> str:
    """The 05.11.26 state, synthetic: floating series, one occurrence moved +30 min
    and written with a Windows TZID, AND excluded via EXDATE (after deleting the
    duplicate in Thunderbird)."""
    d = friday()
    moved = d + dt.timedelta(weeks=1)
    people = _people(ORG, [ME, CAROL], org_params=";SCHEDULE-AGENT=CLIENT")
    master = vevent(uid, stamp(d, 11), stamp(d, 11, 25), rrule="FREQ=WEEKLY;COUNT=8", exdates=[stamp(moved, 11)], people=people, seq=1)
    override = vevent(uid, stamp(moved, 11, 30), stamp(moved, 11, 55), tzid="W. Europe Standard Time",
                      rid=stamp(moved, 11), rid_tzid="W. Europe Standard Time", people=people, seq=3)
    return wrap(master, override, WIN_TZ)


def move_mail(uid: str = "incident-1") -> str:
    """The organizer's update for one occurrence (as Exchange sends it): METHOD:REQUEST,
    RECURRENCE-ID with a Windows TZID, wrapped in a MIME mail."""
    d = friday()
    moved = d + dt.timedelta(weeks=1)
    people = _people(ORG, [ME, CAROL], my_status="NEEDS-ACTION")
    ics = ("BEGIN:VCALENDAR\nMETHOD:REQUEST\nPRODID:Microsoft Exchange Server 2010\nVERSION:2.0\n" + WIN_TZ +
           vevent(uid, stamp(moved, 11, 30), stamp(moved, 11, 55), tzid="W. Europe Standard Time",
                  rid=stamp(moved, 11), rid_tzid="W. Europe Standard Time", people=people, seq=3) + "END:VCALENDAR\n")
    return (
        "From: Org <organizer@external.test>\nTo: alex@example.test\nSubject: Weekly (moved)\n"
        "MIME-Version: 1.0\nContent-Type: multipart/alternative; boundary=XX\n\n--XX\n"
        "Content-Type: text/plain; charset=utf-8\n\nMoved by 30 minutes.\n--XX\n"
        "Content-Type: text/calendar; charset=utf-8; method=REQUEST\n\n" + ics.replace("\n", "\r\n") + "\n--XX--\n"
    )
