"""Which writes make Nextcloud send iMIP mail? Observed against the local stack."""

from dav import *

alex, bob = client("alex"), client("bob")
CAL = "/remote.php/dav/calendars/alex/personal"
reset("alex", "bob")

STAMP = "DTSTAMP:20261105T090000Z"


def ev(uid, start, end, organizer, attendees, partstat="ACCEPTED", extra="", seq=0, org_params="", att_params=""):
    atts = "\n".join(
        f"ATTENDEE;CN={a.split('@')[0]};PARTSTAT={partstat if a.startswith('alex') else 'NEEDS-ACTION'};RSVP=TRUE{att_params}:mailto:{a}"
        for a in attendees)
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//spike//EN
BEGIN:VEVENT
UID:{uid}
{STAMP}
DTSTART;TZID=Europe/Berlin:{start}
DTEND;TZID=Europe/Berlin:{end}
SUMMARY:{uid}
SEQUENCE:{seq}
ORGANIZER;CN=org{org_params}:mailto:{organizer}
{atts}
{extra}END:VEVENT
END:VCALENDAR
""".replace("\n\n", "\n")


class R:
    def __init__(self, r, etag):
        self.r, self.headers = r, {"etag": etag}


def step(label, r):
    print(f"\n## {label}")
    show(r, body=r.status_code >= 400)
    print_mails()
    etag = r.headers.get("etag")
    if r.request.method == "PUT" and r.status_code < 300 and not etag:
        h = alex.head(r.request.url.path)
        etag = h.headers.get("etag")
        print(f"  (no ETag on PUT response; HEAD gives {etag})")
    return R(r, etag)


# ---- A: alex is ATTENDEE, external organizer (the Exchange invite case) ----
u = "A-ext-org"
p = f"{CAL}/{u}.ics"
r = step("A1 create as attendee, PARTSTAT=ACCEPTED", put(alex, p, ev(u, "20261110T110000", "20261110T113000", "organizer@external.test", ["alex@example.test", "carol@external.test"]), If_None_Match="*"))
et = r.headers.get("etag")
r = step("A2 move +30min (attendee changes DTSTART)", put(alex, p, ev(u, "20261110T113000", "20261110T120000", "organizer@external.test", ["alex@example.test", "carol@external.test"]), If_Match=et))
et = r.headers.get("etag")
r = step("A3 extend to 2.5h (attendee changes DTEND)", put(alex, p, ev(u, "20261110T113000", "20261110T140000", "organizer@external.test", ["alex@example.test", "carol@external.test"]), If_Match=et))
et = r.headers.get("etag")
r = step("A4 stale If-Match", put(alex, p, ev(u, "20261110T113000", "20261110T140000", "organizer@external.test", ["alex@example.test"]), If_Match='"stale"'))
r = step("A5 decline (PARTSTAT=DECLINED)", put(alex, p, ev(u, "20261110T113000", "20261110T140000", "organizer@external.test", ["alex@example.test", "carol@external.test"], partstat="DECLINED"), If_Match=et))
et = r.headers.get("etag")
r = step("A6 delete as attendee (plain DELETE)", alex.delete(p))

u = "A-ext-org-b"
p = f"{CAL}/{u}.ics"
step("A7 create as attendee (TENTATIVE)", put(alex, p, ev(u, "20261111T110000", "20261111T113000", "organizer@external.test", ["alex@example.test"], partstat="TENTATIVE")))
step("A8 delete as attendee with Schedule-Reply: F", alex.delete(p, headers={"Schedule-Reply": "F"}))

u = "A-ext-org-c"
p = f"{CAL}/{u}.ics"
step("A9 create as attendee, ORGANIZER;SCHEDULE-AGENT=CLIENT", put(alex, p, ev(u, "20261112T110000", "20261112T113000", "organizer@external.test", ["alex@example.test"], org_params=";SCHEDULE-AGENT=CLIENT")))
step("A10 decline with ORGANIZER;SCHEDULE-AGENT=CLIENT", put(alex, p, ev(u, "20261112T110000", "20261112T113000", "organizer@external.test", ["alex@example.test"], partstat="DECLINED", org_params=";SCHEDULE-AGENT=CLIENT")))
step("A11 delete with ORGANIZER;SCHEDULE-AGENT=CLIENT", alex.delete(p))

# ---- B: alex is ORGANIZER ----
u = "B-own"
p = f"{CAL}/{u}.ics"
r = step("B1 create as organizer w/ bob (internal) + carol (external)", put(alex, p, ev(u, "20261113T100000", "20261113T110000", "alex@example.test", ["alex@example.test", "bob@example.test", "carol@external.test"])))
r2 = propfind(bob, "/remote.php/dav/calendars/bob/personal/", "<d:getetag/>", "1")
print("  bob's personal calendar hrefs:", [h for h, _, _ in hrefs_with_data(r2.text)])
r = step("B2 organizer moves (DTSTART change, SEQUENCE unchanged)", put(alex, p, ev(u, "20261113T103000", "20261113T113000", "alex@example.test", ["alex@example.test", "bob@example.test", "carol@external.test"])))
r = step("B3 organizer changes only SUMMARY-less noop (same content)", put(alex, p, ev(u, "20261113T103000", "20261113T113000", "alex@example.test", ["alex@example.test", "bob@example.test", "carol@external.test"])))
r = step("B4 delete as organizer", alex.delete(p))

u = "B-own-quiet"
p = f"{CAL}/{u}.ics"
step("B5 create as organizer, attendees SCHEDULE-AGENT=CLIENT", put(alex, p, ev(u, "20261114T100000", "20261114T110000", "alex@example.test", ["alex@example.test", "bob@example.test", "carol@external.test"], att_params=";SCHEDULE-AGENT=CLIENT")))
step("B6 move, attendees SCHEDULE-AGENT=CLIENT", put(alex, p, ev(u, "20261114T120000", "20261114T130000", "alex@example.test", ["alex@example.test", "bob@example.test", "carol@external.test"], att_params=";SCHEDULE-AGENT=CLIENT")))
step("B7 delete, attendees SCHEDULE-AGENT=CLIENT", alex.delete(p))

# ---- C: no ORGANIZER at all (personal block) ----
u = "C-plain"
p = f"{CAL}/{u}.ics"
plain = f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//spike//EN\nBEGIN:VEVENT\nUID:{u}\n{STAMP}\nDTSTART;TZID=Europe/Berlin:20261115T100000\nDTEND;TZID=Europe/Berlin:20261115T110000\nSUMMARY:plain\nEND:VEVENT\nEND:VCALENDAR\n"
step("C1 create, no organizer (no VTIMEZONE in body)", put(alex, p, plain))
print("  stored body:")
print(textwrap.indent(alex.get(p).text, "     "))
step("C2 delete", alex.delete(p))
