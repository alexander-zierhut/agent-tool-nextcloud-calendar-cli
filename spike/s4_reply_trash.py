"""Decline-with-reply, two-phase CLIENT on the attendee side, trashbin via REPORT."""

import re

from dav import *

reset("alex", "bob")
alex, bob = client("alex"), client("bob")
CAL = "/remote.php/dav/calendars/alex/personal"
ORG = "organizer@external.test"


def ev(uid, partstat, lastmod=None, org_params="", seq=0, start="20261210T100000", rrule=None):
    x = (f"LAST-MODIFIED:{lastmod}\n" if lastmod else "") + (f"RRULE:{rrule}\n" if rrule else "")
    return (f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//spike//EN\nBEGIN:VEVENT\nUID:{uid}\nDTSTAMP:20261105T090000Z\n{x}"
            f"DTSTART;TZID=Europe/Berlin:{start}\nDURATION:PT1H\nSUMMARY:{uid}\nSEQUENCE:{seq}\n"
            f"ORGANIZER;CN=org{org_params}:mailto:{ORG}\nATTENDEE;CN=alex;PARTSTAT={partstat}:mailto:alex@example.test\n"
            f"ATTENDEE;CN=carol;PARTSTAT=NEEDS-ACTION:mailto:carol@external.test\nEND:VEVENT\nEND:VCALENDAR\n")


def step(label, r):
    print(f"\n## {label}")
    show(r, body=r.status_code >= 400, limit=600)
    print_mails()
    return r


CL = ";SCHEDULE-AGENT=CLIENT"
u = "R1"; p = f"{CAL}/{u}.ics"
step("R1a import invite quietly (ORGANIZER CLIENT, ACCEPTED)", put(alex, p, ev(u, "ACCEPTED", org_params=CL)))
step("R1b phase 2: strip CLIENT, nothing else", put(alex, p, ev(u, "ACCEPTED")))
step("R1c decline, LAST-MODIFIED bump (server scheduling now on)", put(alex, p, ev(u, "DECLINED", lastmod="20261105T130000Z")))

u = "R2"; p = f"{CAL}/{u}.ics"
step("R2a Thunderbird-like object (ORGANIZER CLIENT, ACCEPTED, LAST-MODIFIED)", put(alex, p, ev(u, "ACCEPTED", org_params=CL, lastmod="20261105T120000Z")))
step("R2b decline + strip CLIENT + LAST-MODIFIED bump in one PUT", put(alex, p, ev(u, "DECLINED", lastmod="20261105T130000Z")))
step("R2c re-accept + LAST-MODIFIED bump", put(alex, p, ev(u, "ACCEPTED", lastmod="20261105T130100Z")))
step("R2d tentative + SEQUENCE unchanged, LAST-MODIFIED bump", put(alex, p, ev(u, "TENTATIVE", lastmod="20261105T130200Z")))

u = "R3"; p = f"{CAL}/{u}.ics"
step("R3a NEEDS-ACTION create", put(alex, p, ev(u, "NEEDS-ACTION")))
step("R3b -> DECLINED with LAST-MODIFIED newly added", put(alex, p, ev(u, "DECLINED", lastmod="20261105T130000Z")))
step("R3c -> DECLINED->ACCEPTED, LAST-MODIFIED bump", put(alex, p, ev(u, "ACCEPTED", lastmod="20261105T130100Z")))
step("R3d -> ACCEPTED->DECLINED, LAST-MODIFIED bump", put(alex, p, ev(u, "DECLINED", lastmod="20261105T130200Z")))

u = "R4"; p = f"{CAL}/{u}.ics"
step("R4a past event, ACCEPTED, create (past events never mail?)", put(alex, p, ev(u, "ACCEPTED", start="20261001T100000")))

# ---- trashbin via calendar-query ----
print("\n## T trashbin via REPORT")
alex.delete(f"{CAL}/R1.ics", headers={"Schedule-Reply": "F"})
print_mails("delete R1")
q = ('<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:nc="http://nextcloud.com/ns">'
     '<d:prop><d:getetag/><nc:deleted-at/><nc:calendar-uri/><c:calendar-data/></d:prop>'
     '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
     '<c:time-range start="20200101T000000Z" end="20300101T000000Z"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>')
r = report(alex, "/remote.php/dav/calendars/alex/trashbin/objects/", q)
show(r, limit=1500)
objs = re.findall(r"<d:href>([^<]+)</d:href>", r.text)
print("  trash objects:", objs)
if objs:
    name = objs[0].rstrip("/").rsplit("/", 1)[-1]
    r = alex.request("MOVE", objs[0], headers={"Destination": f"{BASE}/remote.php/dav/calendars/alex/trashbin/restore/{name}"})
    show(r)
    print_mails("after restore")
    r = propfind(alex, f"{CAL}/", "<d:getetag/>", "1")
    print("  personal after restore:", [h for h, _, _ in hrefs_with_data(r.text)])
    r = report(alex, "/remote.php/dav/calendars/alex/trashbin/objects/", q)
    print("  trash after restore:", re.findall(r"<d:href>([^<]+)</d:href>", r.text))
