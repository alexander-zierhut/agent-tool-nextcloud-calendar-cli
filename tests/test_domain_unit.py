"""Hermetic: time parsing, value forms, occurrence edits, diagnose/repair, import merge,
and the scheduling write rules against a fake server."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import icalendar
import pytest
from samples import (
    ME,
    broken_incident,
    friday,
    invite_series,
    invite_single,
    move_mail,
    own_series,
    personal,
    stamp,
)

from nextcloudcalendar import diagnose as D
from nextcloudcalendar import ical as I
from nextcloudcalendar import itip
from nextcloudcalendar.errors import SchedulingRefused, ValidationError
from nextcloudcalendar.scheduling import Writer
from nextcloudcalendar.timeparse import parse_date, parse_datetime, parse_duration, parse_when

BER = ZoneInfo("Europe/Berlin")
FRI = friday()


def obj(text: str, name: str = "x.ics", cal: str = "personal") -> I.EventObject:
    return I.EventObject.parse(cal, f"/remote.php/dav/calendars/alex/{cal}/{name}", '"e1"', text)


# ---- timeparse ---------------------------------------------------------------

def test_durations():
    assert parse_duration("90m") == dt.timedelta(minutes=90)
    assert parse_duration("1h30m") == dt.timedelta(minutes=90)
    assert parse_duration("2.5h") == dt.timedelta(hours=2, minutes=30)
    assert parse_duration("-1h") == -dt.timedelta(hours=1)
    assert parse_duration("+1d") == dt.timedelta(days=1)
    assert parse_duration("PT1H15M") == dt.timedelta(minutes=75)
    with pytest.raises(ValidationError):
        parse_duration("soon")


def test_dates_and_times():
    assert parse_date("2026-11-06", BER) == dt.date(2026, 11, 6)
    assert parse_date("06.11.2026", BER) == dt.date(2026, 11, 6)
    assert parse_date("fr", BER).weekday() == 4
    d = dt.date(2026, 11, 6)
    assert parse_datetime("11:30", BER, on=d) == dt.datetime(2026, 11, 6, 11, 30, tzinfo=BER)
    assert parse_datetime("2026-11-06 11:30", BER) == dt.datetime(2026, 11, 6, 11, 30, tzinfo=BER)
    assert parse_datetime("2026-11-06T10:30Z", BER).utcoffset() == dt.timedelta(0)
    assert isinstance(parse_when("2026-11-06", BER), dt.date) and not isinstance(parse_when("2026-11-06", BER), dt.datetime)
    with pytest.raises(ValidationError):
        parse_datetime("half past eleven", BER)


# ---- value forms ---------------------------------------------------------------

def test_floating_and_tzid_name_the_same_occurrence():
    o = obj(broken_incident())
    ov = o.overrides()[0]
    assert I.form_of(o.master()["DTSTART"]).kind == "floating"
    assert I.form_of(ov["RECURRENCE-ID"]).kind == "tzid"
    moved = FRI + dt.timedelta(weeks=1)
    assert I.instant_key(ov["RECURRENCE-ID"], BER) == I.instant_key(dt.datetime.combine(moved, dt.time(11)), BER)
    assert o.find_component(dt.datetime.combine(moved, dt.time(11), tzinfo=BER), BER) is ov


def test_make_override_uses_series_form_and_drops_exdate():
    o = obj(invite_series())
    rid = dt.datetime.combine(FRI + dt.timedelta(weeks=1), dt.time(11))  # floating, like the series
    I.add_exdate(o, rid, BER)
    assert len(o.exdate_values()) == 1
    ov = I.make_override(o, rid, BER)
    assert I.form_of(ov["RECURRENCE-ID"]).kind == "floating"
    assert ov.get("RRULE") is None and o.exdate_values() == []


def test_shift_series_moves_rids_with_it():
    o = obj(broken_incident())
    D.repair(o, BER)
    before = I.instant_key(o.overrides()[0]["RECURRENCE-ID"], BER)
    I.shift_series(o, dt.timedelta(minutes=30), BER)
    after = I.instant_key(o.overrides()[0]["RECURRENCE-ID"], BER)
    assert before != after
    assert after in o.series_instances(o.overrides()[0]["RECURRENCE-ID"].dt, BER)
    assert D.check_object(o, BER) == []


def test_roles():
    assert I.role_of(obj(personal()).master(), [ME]).kind == "personal"
    r = I.role_of(obj(invite_single()).master(), [ME])
    assert (r.kind, r.my_status, r.organizer) == ("attendee", "ACCEPTED", "organizer@external.test")
    assert I.role_of(obj(own_series()).master(), [ME]).kind == "organizer"


# ---- diagnose ------------------------------------------------------------------------

def test_diagnose_finds_both_incident_problems_and_repairs_them():
    o = obj(broken_incident())
    codes = sorted(f["code"] for f in D.check_object(o, BER))
    assert codes == ["excluded-but-changed", "occurrence-form-mismatch"]
    done = D.repair(o, BER)
    assert {d["code"] for d in done} == {"excluded-but-changed", "occurrence-form-mismatch"}
    assert D.check_object(o, BER) == []
    ov = o.overrides()[0]
    moved = FRI + dt.timedelta(weeks=1)
    assert ov["RECURRENCE-ID"].to_ical().decode() == f"{moved:%Y%m%d}T110000"
    assert ov["DTSTART"].to_ical().decode() == f"{moved:%Y%m%d}T113000"
    occ = o.occurrences(dt.datetime.combine(moved, dt.time(), tzinfo=BER), dt.datetime.combine(moved, dt.time(23), tzinfo=BER), BER)
    assert [x.start.strftime("%H:%M") for x in occ] == ["11:30"]


def test_orphan_occurrence():
    text = invite_series().replace("END:VCALENDAR", "") + (
        "BEGIN:VEVENT\nUID:series-1\nDTSTAMP:20260101T000000Z\n"
        f"RECURRENCE-ID:{stamp(FRI + dt.timedelta(days=1), 11)}\nDTSTART:{stamp(FRI + dt.timedelta(days=1), 12)}\n"
        f"DTEND:{stamp(FRI + dt.timedelta(days=1), 13)}\nSUMMARY:x\nEND:VEVENT\nEND:VCALENDAR\n")
    assert [f["code"] for f in D.check_object(obj(text), BER)] == ["orphan-occurrence"]


def test_duplicates_across_calendars():
    a, b = obj(personal("u1"), "a.ics", "personal"), obj(personal("u1"), "b.ics", "work")
    f = D.check_duplicates([a, b])
    assert f[0]["code"] == "duplicate-uid" and f[0]["duplicates"] == ["personal/a.ics", "work/b.ics"]


# ---- import ------------------------------------------------------------------------

def test_merge_occurrence_update_keeps_my_answer_and_aligns_form():
    stored = obj(invite_series("incident-1"))
    from email import message_from_string

    msg = message_from_string(move_mail("incident-1"))
    part = next(p for p in msg.walk() if p.get_content_type() == "text/calendar")
    incoming = icalendar.Calendar.from_ical(part.get_payload())
    comps = itip.by_uid(incoming)["incident-1"]
    edited, notes = itip.merge_request(stored, incoming, comps, [ME], BER)
    ov = edited.overrides()[0]
    assert I.form_of(ov["RECURRENCE-ID"]).kind == "floating"
    assert I.role_of(ov, [ME]).my_status == "ACCEPTED"      # was NEEDS-ACTION in the mail
    assert ov["ORGANIZER"].params.get("SCHEDULE-AGENT") == "CLIENT"
    assert D.check_object(edited, BER) == []
    assert any("time form" in n for n in notes)


def test_stale_series_update_is_skipped():
    stored = obj(invite_series("s").replace("SEQUENCE:0", "SEQUENCE:5"))
    incoming = icalendar.Calendar.from_ical(invite_series("s").replace("SUMMARY:Weekly", "SUMMARY:Old"))
    edited, notes = itip.merge_request(stored, incoming, itip.by_uid(incoming)["s"], [ME], BER)
    assert str(edited.master()["SUMMARY"]) == "Weekly" and "skipped" in notes[0]


def test_cancel_one_occurrence():
    stored = obj(invite_series("s"))
    rid = icalendar.prop.vDDDTypes(dt.datetime.combine(FRI + dt.timedelta(weeks=2), dt.time(11)))
    comp = icalendar.Event()
    comp.add("UID", "s")
    comp["RECURRENCE-ID"] = rid
    edited, _ = itip.apply_cancel(stored, [comp], BER)
    assert str(edited.overrides()[0]["STATUS"]) == "CANCELLED"


# ---- scheduling rules against a fake server -------------------------------------------

class FakeClient:
    def __init__(self):
        self.puts: list[str] = []
        self.deletes: list[dict] = []

    def put(self, href, ics, *, etag=None, create=False):
        self.puts.append(ics)

    def delete(self, href, *, etag=None, schedule_reply=True):
        self.deletes.append({"href": href, "schedule_reply": schedule_reply})


class FakeDav:
    def __init__(self):
        self.client = FakeClient()

    def reload(self, o):
        return I.EventObject.parse(o.calendar, o.href, '"e2"', self.client.puts[-1])

    def delete_object(self, o, *, schedule_reply, etag=None):
        self.client.delete(o.href, etag=etag, schedule_reply=schedule_reply)


def writer():
    return Writer(FakeDav(), [ME], BER)


def test_quiet_attendee_write_turns_server_scheduling_off():
    w = writer()
    orig = obj(invite_single(client=False))
    ed = orig.copy()
    I.set_times(ed.master(), dt.datetime.combine(FRI, dt.time(15), tzinfo=BER), dt.datetime.combine(FRI, dt.time(17), tzinfo=BER), BER)
    rep = w.save(orig, ed, notify=False, action="update")
    assert "SCHEDULE-AGENT=CLIENT" in w.dav.client.puts[-1]
    assert rep.mode == "quiet" and rep.role == "attendee"


def test_attendee_notify_for_time_change_is_refused():
    with pytest.raises(SchedulingRefused):
        writer().save(obj(invite_single()), obj(invite_single()), notify=True, action="move")


def test_attendee_notify_reply_restores_client_scheduling():
    w = writer()
    orig = obj(invite_single(client=True))
    ed = orig.copy()
    I.set_partstat(ed.master(), [ME], "DECLINED")
    w.save(orig, ed, notify=True, action="respond", attendee_notify_ok=True)
    puts = w.dav.client.puts
    assert "SCHEDULE-AGENT=CLIENT" not in puts[-2] and "DECLINED" in puts[-2]   # the one the server replies on
    assert "SCHEDULE-AGENT=CLIENT" in puts[-1]                                   # handed back to the mail client


def test_attendee_notify_without_last_modified_preps_first():
    w = writer()
    orig = obj(invite_single(client=False, lastmod=False))
    ed = orig.copy()
    I.set_partstat(ed.master(), [ME], "DECLINED")
    w.save(orig, ed, notify=True, action="respond", attendee_notify_ok=True)
    puts = w.dav.client.puts
    assert len(puts) == 2 and "LAST-MODIFIED" in puts[0] and "SCHEDULE-AGENT=CLIENT" in puts[0]


def test_organizer_quiet_keeps_sequence_and_last_modified():
    w = writer()
    orig = obj(own_series())
    ed = orig.copy()
    I.touch(ed.master())
    I.bump_sequence(ed.master())
    I.shift_series(ed, dt.timedelta(hours=1), BER)
    w.save(orig, ed, notify=False, action="move")
    stored = icalendar.Calendar.from_ical(w.dav.client.puts[-1])
    m = next(c for c in stored.walk("VEVENT"))
    assert int(m["SEQUENCE"]) == 0 and m["LAST-MODIFIED"].to_ical() == b"20260101T000000Z"


def test_organizer_quiet_new_occurrence_refused_notify_bumps():
    orig = obj(own_series())
    ed = orig.copy()
    rid = dt.datetime.combine(FRI - dt.timedelta(days=2) + dt.timedelta(weeks=1), dt.time(10), tzinfo=BER)
    I.make_override(ed, rid, BER)
    with pytest.raises(SchedulingRefused):
        writer().save(orig, ed, notify=False, action="move")
    w = writer()
    w.save(orig, ed, notify=True, action="move")
    stored = icalendar.Calendar.from_ical(w.dav.client.puts[-1])
    seqs = sorted(int(c["SEQUENCE"]) for c in stored.walk("VEVENT"))
    assert seqs[-1] >= 1


def test_quiet_organizer_delete_sends_schedule_reply_false():
    w = writer()
    w.delete(obj(own_series()), notify=False)
    assert w.dav.client.deletes[-1]["schedule_reply"] is False
    w.delete(obj(own_series()), notify=True)
    assert w.dav.client.deletes[-1]["schedule_reply"] is True


def test_schedule_status_is_stripped_before_put():
    w = writer()
    text = invite_single(client=False).replace("ATTENDEE;CN=alex;", "ATTENDEE;CN=alex;SCHEDULE-STATUS=1.1;")
    orig = obj(text)
    w.save(orig, orig.copy(), notify=False, action="update")
    assert "SCHEDULE-STATUS" not in w.dav.client.puts[-1]
