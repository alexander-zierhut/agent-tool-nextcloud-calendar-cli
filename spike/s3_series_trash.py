"""Single occurrences of series, LAST-MODIFIED as organizer, trashbin, sync-collection."""

import re

from dav import *

reset("alex", "bob")
alex, bob = client("alex"), client("bob")
CAL = "/remote.php/dav/calendars/alex/personal"
ATTS = ["alex@example.test", "bob@example.test", "carol@external.test"]


def comp(uid, start, end, organizer, attendees, seq=0, lastmod=None, rrule=None, rid=None, exdate=None, org_params="", att_params=""):
    atts = "\n".join(
        f"ATTENDEE;CN={a.split('@')[0]};PARTSTAT={'ACCEPTED' if a.startswith('alex') else 'NEEDS-ACTION'};RSVP=TRUE{att_params}:mailto:{a}"
        for a in attendees)
    x = ""
    if lastmod: x += f"LAST-MODIFIED:{lastmod}\n"
    if rrule: x += f"RRULE:{rrule}\n"
    if rid: x += f"RECURRENCE-ID;TZID=Europe/Berlin:{rid}\n"
    if exdate: x += f"EXDATE;TZID=Europe/Berlin:{exdate}\n"
    return (f"BEGIN:VEVENT\nUID:{uid}\nDTSTAMP:20261105T090000Z\n{x}DTSTART;TZID=Europe/Berlin:{start}\n"
            f"DTEND;TZID=Europe/Berlin:{end}\nSUMMARY:{uid}\nSEQUENCE:{seq}\nORGANIZER;CN=org{org_params}:mailto:{organizer}\n{atts}\nEND:VEVENT\n")


def cal(*comps):
    return "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//spike//EN\n" + "".join(comps) + "END:VCALENDAR\n"


def step(label, r):
    print(f"\n## {label}")
    show(r, body=r.status_code >= 400, limit=600)
    print_mails()
    return r


def bob_copy():
    r = propfind(bob, "/remote.php/dav/calendars/bob/personal/", "<d:getetag/>", "1")
    for href, _, _ in hrefs_with_data(r.text):
        if href.endswith(".ics"):
            data = bob.get(href).text.replace("\r\n ", "")
            print("     bob has:", [ln for ln in data.splitlines() if ln.startswith(("DTSTART", "RECURRENCE-ID", "EXDATE", "SEQUENCE", "STATUS"))])


RR = "FREQ=WEEKLY;COUNT=4"
# ---- G: attendee, single occurrence ----
u = "G"; p = f"{CAL}/{u}.ics"; ORG = "organizer@external.test"
step("G0 attendee series create, NEEDS-ACTION->ACCEPTED quietly", put(alex, p, cal(comp(u, "20261201T100000", "20261201T110000", ORG, ["alex@example.test"], rrule=RR))))
step("G1 attendee adds override (moves 08.12. +1h), no CLIENT", put(alex, p, cal(
    comp(u, "20261201T100000", "20261201T110000", ORG, ["alex@example.test"], rrule=RR),
    comp(u, "20261208T110000", "20261208T120000", ORG, ["alex@example.test"], rid="20261208T100000"))))
step("G2 attendee drops one occurrence via EXDATE, no CLIENT", put(alex, p, cal(
    comp(u, "20261201T100000", "20261201T110000", ORG, ["alex@example.test"], rrule=RR, exdate="20261215T100000"),
    comp(u, "20261208T110000", "20261208T120000", ORG, ["alex@example.test"], rid="20261208T100000"))))

# ---- H: organizer series with bob + carol ----
u = "H"; p = f"{CAL}/{u}.ics"; ME = "alex@example.test"
step("H0 organizer series create (mails expected)", put(alex, p, cal(comp(u, "20261202T100000", "20261202T110000", ME, ATTS, rrule=RR))))
bob_copy()
step("H1 organizer adds override (09.12. +1h), SEQUENCE 0", put(alex, p, cal(
    comp(u, "20261202T100000", "20261202T110000", ME, ATTS, rrule=RR),
    comp(u, "20261209T110000", "20261209T120000", ME, ATTS, rid="20261209T100000"))))
bob_copy()
step("H2 organizer EXDATEs 16.12., SEQUENCE 0", put(alex, p, cal(
    comp(u, "20261202T100000", "20261202T110000", ME, ATTS, rrule=RR, exdate="20261216T100000"),
    comp(u, "20261209T110000", "20261209T120000", ME, ATTS, rid="20261209T100000"))))
bob_copy()
step("H3 organizer moves override again with LAST-MODIFIED bump only", put(alex, p, cal(
    comp(u, "20261202T100000", "20261202T110000", ME, ATTS, rrule=RR, exdate="20261216T100000"),
    comp(u, "20261209T120000", "20261209T130000", ME, ATTS, rid="20261209T100000", lastmod="20261105T120000Z"))))
bob_copy()
step("H4 organizer adds override 23.12. with temporary SCHEDULE-AGENT=CLIENT", put(alex, p, cal(
    comp(u, "20261202T100000", "20261202T110000", ME, ATTS, rrule=RR, exdate="20261216T100000", att_params=";SCHEDULE-AGENT=CLIENT"),
    comp(u, "20261209T120000", "20261209T130000", ME, ATTS, rid="20261209T100000", lastmod="20261105T120000Z", att_params=";SCHEDULE-AGENT=CLIENT"),
    comp(u, "20261223T080000", "20261223T090000", ME, ATTS, rid="20261223T100000", att_params=";SCHEDULE-AGENT=CLIENT"))))
bob_copy()
step("H5 strip CLIENT again, nothing else changed", put(alex, p, cal(
    comp(u, "20261202T100000", "20261202T110000", ME, ATTS, rrule=RR, exdate="20261216T100000"),
    comp(u, "20261209T120000", "20261209T130000", ME, ATTS, rid="20261209T100000", lastmod="20261105T120000Z"),
    comp(u, "20261223T080000", "20261223T090000", ME, ATTS, rid="20261223T100000"))))
bob_copy()

# ---- T: trashbin ----
print("\n## T trashbin")
r = alex.request("PROPFIND", "/remote.php/dav/calendars/alex/trashbin/", headers={"Depth": "1"})
show(r, limit=800)
r = propfind(alex, "/remote.php/dav/calendars/alex/trashbin/objects/",
             "<d:getetag/><nc:calendar-uri/><nc:deleted-at/><c:calendar-data/>".replace("nc:", "x:").replace("<x:", '<x:').replace("x:", "nc:"), "1")
r = alex.request("PROPFIND", "/remote.php/dav/calendars/alex/trashbin/objects/", headers={"Depth": "1", "Content-Type": "application/xml"},
                 content='<d:propfind xmlns:d="DAV:" xmlns:nc="http://nextcloud.com/ns" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><nc:calendar-uri/><nc:deleted-at/><c:calendar-data/></d:prop></d:propfind>')
show(r, limit=2500)
objs = re.findall(r"<d:href>([^<]+\.ics)</d:href>", r.text)
print("  trash objects:", objs)
if objs:
    name = objs[0].rsplit("/", 1)[-1]
    r = alex.request("MOVE", objs[0], headers={"Destination": f"http://127.0.0.1:8089/remote.php/dav/calendars/alex/trashbin/restore/{name}"})
    show(r)
    print_mails("after restore")
    r = propfind(alex, f"{CAL}/", "<d:getetag/>", "1")
    print("  personal after restore:", [h for h, _, _ in hrefs_with_data(r.text)])

# ---- S: sync-collection ----
print("\n## S sync-collection")
tok = re.search(r"<d:sync-token>([^<]+)", propfind(alex, f"{CAL}/", "<d:sync-token/>").text).group(1)
print("  token:", tok)
put(alex, f"{CAL}/S.ics", cal(comp("S", "20261203T100000", "20261203T110000", ME, [ME])))
r = report(alex, f"{CAL}/", f'<d:sync-collection xmlns:d="DAV:"><d:sync-token>{tok}</d:sync-token><d:sync-level>1</d:sync-level><d:prop><d:getetag/></d:prop></d:sync-collection>')
show(r, limit=1200)
