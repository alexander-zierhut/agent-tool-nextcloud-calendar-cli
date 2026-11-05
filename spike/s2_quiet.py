"""Quiet-write mechanics, internal delivery, and the 05.11.26 incident replay."""

import re
import sys

from dav import *

reset("alex", "bob")
alex, bob = client("alex"), client("bob")
CAL = "/remote.php/dav/calendars/alex/personal"
SCRATCH = sys.argv[1]


def ev(uid, start, end, organizer, attendees, partstat="ACCEPTED", seq=0, lastmod=None, org_params="", att_params="", status=None):
    atts = "\n".join(
        f"ATTENDEE;CN={a.split('@')[0]};PARTSTAT={partstat if a.startswith('alex') else 'NEEDS-ACTION'};RSVP=TRUE{att_params}:mailto:{a}"
        for a in attendees)
    lm = f"LAST-MODIFIED:{lastmod}\n" if lastmod else ""
    st = f"STATUS:{status}\n" if status else ""
    return (f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//spike//EN\nBEGIN:VEVENT\nUID:{uid}\nDTSTAMP:20261105T090000Z\n{lm}{st}"
            f"DTSTART;TZID=Europe/Berlin:{start}\nDTEND;TZID=Europe/Berlin:{end}\nSUMMARY:{uid}\nSEQUENCE:{seq}\n"
            f"ORGANIZER;CN=org{org_params}:mailto:{organizer}\n{atts}\nEND:VEVENT\nEND:VCALENDAR\n")


def step(label, r):
    print(f"\n## {label}")
    show(r, body=r.status_code >= 400)
    print_mails()
    return r


def stored(c, path, pat="ATTENDEE|ORGANIZER|SEQUENCE|DTSTART|STATUS|LAST-MOD"):
    txt = c.get(path).text
    for ln in txt.replace("\r\n ", "").splitlines():
        if re.match(pat, ln):
            print("     |", ln[:160])


def bob_copy():
    r = report(bob, "/remote.php/dav/calendars/bob/personal/",
               '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop>'
               '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"/></c:comp-filter></c:filter></c:calendar-query>')
    for href, _, data in hrefs_with_data(r.text):
        lines = [ln for ln in data.splitlines() if ln.startswith(("DTSTART", "SEQUENCE", "STATUS", "SUMMARY"))]
        print("     bob has:", href.rsplit("/", 1)[-1], lines)
    if not hrefs_with_data(r.text):
        print("     bob has: nothing")


ORG, ATT = "organizer@external.test", ["alex@example.test"]

u = "D"; p = f"{CAL}/{u}.ics"
step("D1 attendee create with PARTSTAT=NEEDS-ACTION", put(alex, p, ev(u, "20261117T100000", "20261117T110000", ORG, ATT, partstat="NEEDS-ACTION")))
step("D2 -> ACCEPTED, SEQUENCE+LAST-MODIFIED unchanged", put(alex, p, ev(u, "20261117T100000", "20261117T110000", ORG, ATT)))
stored(alex, p)
step("D3 -> DECLINED with LAST-MODIFIED set", put(alex, p, ev(u, "20261117T100000", "20261117T110000", ORG, ATT, partstat="DECLINED", lastmod="20261105T100000Z")))
step("D4 -> ACCEPTED with LAST-MODIFIED bumped", put(alex, p, ev(u, "20261117T100000", "20261117T110000", ORG, ATT, lastmod="20261105T100100Z")))
step("D5 attendee moves +1h with LAST-MODIFIED bumped (partstat unchanged)", put(alex, p, ev(u, "20261117T110000", "20261117T120000", ORG, ATT, lastmod="20261105T100200Z")))
step("D6 attendee DELETE of ACCEPTED event, no header", alex.delete(p))

u = "D-b"; p = f"{CAL}/{u}.ics"
step("D7 attendee create ACCEPTED w/ LAST-MODIFIED (Thunderbird-like)", put(alex, p, ev(u, "20261118T100000", "20261118T110000", ORG, ATT, lastmod="20261105T100000Z")))
step("D8 attendee DELETE with LAST-MODIFIED present, no header", alex.delete(p))

ATTS = ["alex@example.test", "bob@example.test", "carol@external.test"]
u = "E"; p = f"{CAL}/{u}.ics"
step("E1 organizer create, attendees SCHEDULE-AGENT=CLIENT", put(alex, p, ev(u, "20261119T100000", "20261119T110000", "alex@example.test", ATTS, att_params=";SCHEDULE-AGENT=CLIENT")))
bob_copy()
step("E2 strip SCHEDULE-AGENT=CLIENT, nothing else changed", put(alex, p, ev(u, "20261119T100000", "20261119T110000", "alex@example.test", ATTS)))
stored(alex, p)
bob_copy()
step("E3 organizer moves, SEQUENCE unchanged", put(alex, p, ev(u, "20261119T120000", "20261119T130000", "alex@example.test", ATTS)))
bob_copy()
step("E4 organizer moves, SEQUENCE 0->1", put(alex, p, ev(u, "20261119T140000", "20261119T150000", "alex@example.test", ATTS, seq=1)))
stored(alex, p)
bob_copy()
step("E5 organizer sets STATUS:CANCELLED + SEQUENCE 2", put(alex, p, ev(u, "20261119T140000", "20261119T150000", "alex@example.test", ATTS, seq=2, status="CANCELLED")))
bob_copy()
step("E6 organizer DELETE with Schedule-Reply: F", alex.delete(p, headers={"Schedule-Reply": "F"}))
bob_copy()

# ---- F: replay the 05.11.26 incident with the real objects (local stack only) ----
import pathlib
orig = pathlib.Path(SCRATCH, "series.backup.ics").read_text()
fix1 = pathlib.Path(SCRATCH, "series.new.ics").read_text()
fix2 = pathlib.Path(SCRATCH, "series2.new.ics").read_text()
p = f"{CAL}/incident.ics"
for label, body in (("F1 create as Thunderbird stored it", orig), ("F2 fix 1: drop EXDATE", fix1), ("F3 fix 2: floating override", fix2)):
    step(label, put(alex, p, body.replace("\r\n", "\n")))
    r = report(alex, CAL + "/",
               '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><c:calendar-data>'
               '<c:expand start="20261102T000000Z" end="20261109T000000Z"/></c:calendar-data></d:prop>'
               '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
               '<c:time-range start="20261102T000000Z" end="20261109T000000Z"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
    for href, _, data in hrefs_with_data(r.text):
        if "incident" in href:
            inst = [ln for ln in data.splitlines() if ln.startswith(("DTSTART", "RECURRENCE-ID"))]
            print("     server expand 02.-09.11.:", inst)
