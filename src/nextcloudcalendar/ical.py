"""The calendar-object model: value forms, occurrences, and edit primitives.

Pure (no network). Everything that knows iCalendar lives here, so commands
never touch a property directly.

The single most important idea in this module is the **value form** of a
date-time. The same instant can be written four ways, and clients disagree about
whether two of them name the same occurrence:

    DTSTART;VALUE=DATE:20261106                 date      (all-day)
    DTSTART:20261106T110000                     floating  (wall clock, no zone)
    DTSTART:20261106T100000Z                    utc
    DTSTART;TZID=Europe/Berlin:20261106T110000  tzid

A RECURRENCE-ID must be written in the *same form* as the master's DTSTART
(RFC 5545 §3.8.4.4). Exchange invites are often stored floating by Thunderbird,
while a later "this occurrence moved" mail arrives with a TZID. The instants are
equal, the forms are not, and Thunderbird then shows the original occurrence AND
the moved one (observed 05.11.26, reproduced against Nextcloud 35). So every
write below goes through `write_dt`, which writes in a given form, and every
comparison goes through `instant_key`, which compares instants, not text.
"""

from __future__ import annotations

import copy
import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import icalendar
import recurring_ical_events

UTC = dt.timezone.utc
_SERIES_ONLY = ("RRULE", "RDATE", "EXDATE", "EXRULE")


# ---------------------------------------------------------------------------
# value forms
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Form:
    """How a date-time property is written: 'date' | 'floating' | 'utc' | 'tzid'."""

    kind: str
    tzid: str | None = None
    tzinfo: Any = None  # tzinfo for kind == 'tzid' (zoneinfo, or dateutil for embedded VTIMEZONEs)

    def describe(self) -> str:
        return f"TZID={self.tzid}" if self.kind == "tzid" else self.kind


def form_of(prop: Any) -> Form:
    """The form a parsed date/date-time property (vDDDTypes) is written in."""
    value = prop.dt if hasattr(prop, "dt") else prop
    params = getattr(prop, "params", {}) or {}
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return Form("date")
    if value.tzinfo is None:
        return Form("floating")
    tzid = params.get("TZID")
    if tzid:
        return Form("tzid", str(tzid), value.tzinfo)
    if value.utcoffset() == dt.timedelta(0) and _is_utc(value.tzinfo):
        return Form("utc")
    return Form("tzid", _tz_name(value.tzinfo), value.tzinfo)


def _is_utc(tz: Any) -> bool:
    name = _tz_name(tz)
    return name in ("UTC", "Etc/UTC", "Z", "GMT") or tz is UTC


def _tz_name(tz: Any) -> str:
    for attr in ("key", "zone", "_tzid"):
        v = getattr(tz, attr, None)
        if isinstance(v, str):
            return v
    return str(tz)


def to_aware(value: dt.date | dt.datetime, local: dt.tzinfo) -> dt.date | dt.datetime:
    """Floating -> wall-clock in *local*; aware stays; dates stay dates."""
    if isinstance(value, dt.datetime) and value.tzinfo is None:
        return value.replace(tzinfo=local)
    return value


def instant_key(value: Any, local: dt.tzinfo) -> str:
    """A form-independent identity for an occurrence start (RECURRENCE-ID, EXDATE).

    Dates compare as dates; date-times as UTC instants, floating ones read in the
    user's zone. Two values with equal keys name the same occurrence for a human,
    whatever their textual form.
    """
    v = value.dt if hasattr(value, "dt") else value
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return v.isoformat()
    return to_aware(v, local).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def convert(value: dt.date | dt.datetime, form: Form, local: dt.tzinfo) -> dt.date | dt.datetime:
    """Re-express an instant in *form* (returns the python value to write)."""
    if form.kind == "date":
        if isinstance(value, dt.datetime):
            return to_aware(value, local).astimezone(local).date()
        return value
    if not isinstance(value, dt.datetime):
        value = dt.datetime.combine(value, dt.time(0, 0))
    aware = to_aware(value, local)
    if form.kind == "floating":
        return aware.astimezone(local).replace(tzinfo=None)
    if form.kind == "utc":
        return aware.astimezone(UTC)
    return aware.astimezone(form.tzinfo).replace(tzinfo=None)  # wall clock in TZID


def write_dt(comp: icalendar.cal.Component, name: str, value: dt.date | dt.datetime, form: Form, local: dt.tzinfo) -> None:
    """Replace property *name* with *value* written in *form*."""
    comp.pop(name, None)
    comp.add(name, convert(value, form, local), parameters=_form_params(form))


def _form_params(form: Form) -> dict[str, str]:
    if form.kind == "tzid":
        return {"TZID": form.tzid}
    if form.kind == "date":
        return {"VALUE": "DATE"}
    return {}


def resolve_zone(name: str | None) -> dt.tzinfo:
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


# ---------------------------------------------------------------------------
# the object
# ---------------------------------------------------------------------------

@dataclass
class EventObject:
    """One calendar object resource: a .ics file holding one UID (master + overrides)."""

    calendar: str            # calendar slug, e.g. "personal"
    href: str                # server path of the .ics
    etag: str | None
    cal: icalendar.Calendar
    calendar_name: str | None = None

    @classmethod
    def parse(cls, calendar: str, href: str, etag: str | None, text: str, calendar_name: str | None = None) -> EventObject:
        return cls(calendar, href, etag, icalendar.Calendar.from_ical(text), calendar_name)

    # ---- structure ---------------------------------------------------
    @property
    def name(self) -> str:
        return self.href.rstrip("/").rsplit("/", 1)[-1]

    @property
    def id(self) -> str:
        return f"{self.calendar}/{self.name}"

    def events(self) -> list[icalendar.cal.Component]:
        return [c for c in self.cal.subcomponents if c.name == "VEVENT"]

    @property
    def uid(self) -> str | None:
        for c in self.events():
            if c.get("UID"):
                return str(c.get("UID"))
        return None

    def master(self) -> icalendar.cal.Component | None:
        for c in self.events():
            if c.get("RECURRENCE-ID") is None:
                return c
        return None

    def overrides(self) -> list[icalendar.cal.Component]:
        return [c for c in self.events() if c.get("RECURRENCE-ID") is not None]

    def is_recurring(self) -> bool:
        m = self.master()
        return bool(m is not None and (m.get("RRULE") or m.get("RDATE"))) or len(self.overrides()) > 0

    def to_ical(self) -> str:
        return self.cal.to_ical().decode("utf-8")

    def copy(self) -> EventObject:
        return EventObject(self.calendar, self.href, self.etag, copy.deepcopy(self.cal), self.calendar_name)

    # ---- occurrences -------------------------------------------------
    def occurrences(self, start: dt.datetime, end: dt.datetime, local: dt.tzinfo) -> list[Occurrence]:
        """Every occurrence overlapping [start, end), overrides applied."""
        out: list[Occurrence] = []
        try:
            items = recurring_ical_events.of(self.cal, skip_bad_series=True).between(start, end)
        except Exception:  # a malformed series must not hide the rest of the calendar
            items = [c for c in self.events()]
        recurring = self.is_recurring()
        for comp in items:
            s = comp.get("DTSTART")
            if s is None:
                continue
            e = comp.get("DTEND")
            s_val = s.dt
            if e is not None:
                e_val = e.dt
            elif comp.get("DURATION") is not None:
                e_val = s_val + comp.get("DURATION").dt
            elif isinstance(s_val, dt.datetime):
                e_val = s_val
            else:
                e_val = s_val + dt.timedelta(days=1)
            rid = comp.get("RECURRENCE-ID")
            out.append(Occurrence(
                obj=self,
                comp=comp,
                start=to_aware(s_val, local),
                end=to_aware(e_val, local),
                recurrence_id=to_aware(rid.dt, local) if (rid is not None and recurring) else None,
                floating=isinstance(s_val, dt.datetime) and s_val.tzinfo is None,
            ))
        out.sort(key=lambda o: _sort_key(o.start))
        return out

    def find_component(self, rid_value: Any, local: dt.tzinfo) -> icalendar.cal.Component | None:
        """The override whose RECURRENCE-ID names the same occurrence as *rid_value* (form-tolerant)."""
        key = instant_key(rid_value, local)
        for c in self.overrides():
            if instant_key(c.get("RECURRENCE-ID"), local) == key:
                return c
        return None

    def exdate_values(self) -> list[Any]:
        m = self.master()
        if m is None:
            return []
        raw = m.get("EXDATE")
        if raw is None:
            return []
        lists = raw if isinstance(raw, list) else [raw]
        out = []
        for lst in lists:
            for d in lst.dts:
                out.append(d)
        return out

    def series_instances(self, around: dt.date | dt.datetime, local: dt.tzinfo, days: int = 2) -> list[str]:
        """instant_keys of the master's own instances (overrides and EXDATEs ignored) near *around*."""
        m = self.master()
        if m is None:
            return []
        bare = icalendar.Calendar()
        for c in self.cal.subcomponents:
            if c.name == "VTIMEZONE":
                bare.add_component(c)
        mm = copy.deepcopy(m)
        mm.pop("EXDATE", None)
        bare.add_component(mm)
        a = around if isinstance(around, dt.datetime) else dt.datetime.combine(around, dt.time())
        a = to_aware(a, local)
        try:
            items = recurring_ical_events.of(bare).between(a - dt.timedelta(days=days), a + dt.timedelta(days=days))
        except Exception:
            return []
        return [instant_key(c.get("DTSTART"), local) for c in items]


def _sort_key(v: dt.date | dt.datetime) -> dt.datetime:
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    return dt.datetime.combine(v, dt.time(), tzinfo=UTC)


@dataclass
class Occurrence:
    obj: EventObject
    comp: icalendar.cal.Component
    start: dt.date | dt.datetime
    end: dt.date | dt.datetime
    recurrence_id: dt.date | dt.datetime | None
    floating: bool = False

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, dt.datetime)

    @property
    def is_override(self) -> bool:
        return self.recurrence_id is not None and self.obj.find_component(self.comp.get("RECURRENCE-ID"), UTC) is not None


# ---------------------------------------------------------------------------
# people
# ---------------------------------------------------------------------------

def address(value: Any) -> str:
    """'mailto:Alex@Example.com' -> 'alex@example.com'."""
    s = str(value or "").strip()
    if s.lower().startswith("mailto:"):
        s = s[7:]
    return s.lower()


@dataclass
class Role:
    """Who I am in this event: 'organizer' | 'attendee' | 'personal'."""

    kind: str
    my_status: str | None = None          # my PARTSTAT, if I am an attendee
    organizer: str | None = None
    others: list[str] = field(default_factory=list)  # attendees that are not me

    @property
    def has_others(self) -> bool:
        return bool(self.others) or (self.kind == "attendee")


def role_of(comp: icalendar.cal.Component, me: Iterable[str]) -> Role:
    mine = {address(a) for a in me}
    org = comp.get("ORGANIZER")
    org_addr = address(org) if org is not None else None
    atts = comp.get("ATTENDEE")
    atts = atts if isinstance(atts, list) else ([atts] if atts is not None else [])
    my_status = None
    others = []
    for a in atts:
        addr = address(a)
        if addr in mine:
            my_status = str(a.params.get("PARTSTAT", "NEEDS-ACTION")).upper()
        else:
            others.append(addr)
    if org_addr is None:
        return Role("personal", my_status, None, others)
    if org_addr in mine:
        return Role("organizer" if others else "personal", my_status, org_addr, others)
    return Role("attendee", my_status or "NEEDS-ACTION", org_addr, others)


def attendee_props(comp: icalendar.cal.Component) -> list[Any]:
    atts = comp.get("ATTENDEE")
    return atts if isinstance(atts, list) else ([atts] if atts is not None else [])


# ---------------------------------------------------------------------------
# edit primitives
# ---------------------------------------------------------------------------

def now_utc() -> dt.datetime:
    return dt.datetime.now(UTC).replace(microsecond=0)


def touch(comp: icalendar.cal.Component, *, last_modified: bool = True) -> None:
    """Refresh DTSTAMP (always) and LAST-MODIFIED (only when allowed)."""
    comp.pop("DTSTAMP", None)
    comp.add("DTSTAMP", now_utc())
    if last_modified:
        comp.pop("LAST-MODIFIED", None)
        comp.add("LAST-MODIFIED", now_utc())


def bump_sequence(comp: icalendar.cal.Component, floor: int = 0) -> int:
    seq = max(int(comp.get("SEQUENCE", 0) or 0) + 1, floor)
    comp.pop("SEQUENCE", None)
    comp.add("SEQUENCE", seq)
    return seq


def duration_of(comp: icalendar.cal.Component) -> dt.timedelta:
    s = comp.get("DTSTART").dt
    if comp.get("DTEND") is not None:
        e = comp.get("DTEND").dt
        if isinstance(s, dt.datetime) and isinstance(e, dt.datetime):
            if (s.tzinfo is None) != (e.tzinfo is None):
                e = e.replace(tzinfo=s.tzinfo)
        return e - s
    if comp.get("DURATION") is not None:
        return comp.get("DURATION").dt
    return dt.timedelta(0) if isinstance(s, dt.datetime) else dt.timedelta(days=1)


def set_times(comp: icalendar.cal.Component, start: dt.date | dt.datetime, end: dt.date | dt.datetime, local: dt.tzinfo) -> None:
    """Write new start/end into *comp*, keeping each property's existing form
    (and DURATION instead of DTEND if that is what the component uses)."""
    sform = form_of(comp.get("DTSTART"))
    write_dt(comp, "DTSTART", start, sform, local)
    if comp.get("DURATION") is not None and comp.get("DTEND") is None:
        comp.pop("DURATION")
        comp.add("DURATION", _diff(end, start, local))
    else:
        eprop = comp.get("DTEND")
        eform = form_of(eprop) if eprop is not None else sform
        write_dt(comp, "DTEND", end, eform, local)


def _diff(end: Any, start: Any, local: dt.tzinfo) -> dt.timedelta:
    if isinstance(end, dt.datetime) and isinstance(start, dt.datetime):
        return to_aware(end, local) - to_aware(start, local)
    return end - start


def make_override(obj: EventObject, rid_value: Any, local: dt.tzinfo) -> icalendar.cal.Component:
    """Create (and attach) an override for the occurrence *rid_value* of the series,
    a copy of the master with RECURRENCE-ID written in the master's DTSTART form.

    Also removes an EXDATE that names the same occurrence: an EXDATE plus an
    override for one occurrence is the "both vanished" state (Thunderbird hides
    both, Nextcloud still serves the override)."""
    master = obj.master()
    if master is None:
        raise ValueError("this object has no master event to derive an occurrence from")
    mform = form_of(master.get("DTSTART"))
    rid = rid_value.dt if hasattr(rid_value, "dt") else rid_value
    ov = copy.deepcopy(master)
    for key in _SERIES_ONLY + ("DTSTART", "DTEND", "DURATION", "RECURRENCE-ID"):
        while ov.get(key) is not None:
            ov.pop(key)
    dur = duration_of(master)
    start = convert(rid, mform, local)
    write_dt(ov, "RECURRENCE-ID", rid, mform, local)
    write_dt(ov, "DTSTART", rid, mform, local)
    end_prop_form = form_of(master.get("DTEND")) if master.get("DTEND") is not None else mform
    if master.get("DURATION") is not None and master.get("DTEND") is None:
        ov.add("DURATION", dur)
    else:
        write_dt(ov, "DTEND", to_aware(start, local) + dur if isinstance(start, dt.datetime) else start + dur, end_prop_form, local)
    remove_exdate(obj, rid, local)
    obj.cal.add_component(ov)
    return ov


def remove_exdate(obj: EventObject, rid_value: Any, local: dt.tzinfo) -> bool:
    """Drop every EXDATE value naming the same occurrence as *rid_value*. True if one was removed."""
    master = obj.master()
    if master is None or master.get("EXDATE") is None:
        return False
    key = instant_key(rid_value, local)
    raw = master.get("EXDATE")
    lists = raw if isinstance(raw, list) else [raw]
    keep: list[tuple[Any, dict]] = []
    removed = False
    for lst in lists:
        params = dict(lst.params) if getattr(lst, "params", None) else {}
        for d in lst.dts:
            if instant_key(d.dt, local) == key:
                removed = True
            else:
                keep.append((d.dt, params))
    if removed:
        master.pop("EXDATE")
        for value, params in keep:
            master.add("EXDATE", [value], parameters=params)
    return removed


def add_exdate(obj: EventObject, rid_value: Any, local: dt.tzinfo) -> None:
    """Exclude one occurrence from the series (EXDATE in the master's DTSTART form),
    dropping its override if one exists."""
    master = obj.master()
    if master is None:
        raise ValueError("this object has no master event")
    rid = rid_value.dt if hasattr(rid_value, "dt") else rid_value
    ov = obj.find_component(rid, local)
    if ov is not None:
        obj.cal.subcomponents.remove(ov)
    if any(instant_key(v.dt, local) == instant_key(rid, local) for v in obj.exdate_values()):
        return
    mform = form_of(master.get("DTSTART"))
    master.add("EXDATE", [convert(rid, mform, local)], parameters=_form_params(mform))


def shift_series(obj: EventObject, delta: dt.timedelta, local: dt.tzinfo) -> None:
    """Move a whole series by *delta*: master start/end, its EXDATEs/RDATEs, an
    UNTIL bound, and every override's RECURRENCE-ID (so overrides keep pointing at
    their occurrence). Overrides keep their own, already-changed times."""
    master = obj.master()
    if master is None:
        raise ValueError("this object has no master event")
    s = master.get("DTSTART").dt
    start = to_aware(s, local) + delta if isinstance(s, dt.datetime) else s + delta
    end = start + duration_of(master)
    set_times(master, start, end, local)
    for name in ("EXDATE", "RDATE"):
        raw = master.get(name)
        if raw is None:
            continue
        lists = raw if isinstance(raw, list) else [raw]
        master.pop(name)
        for lst in lists:
            params = dict(lst.params) if getattr(lst, "params", None) else {}
            for d in lst.dts:
                v = d.dt
                if isinstance(v, dt.datetime):
                    nv = to_aware(v, local) + delta
                    if v.tzinfo is None:
                        nv = nv.astimezone(local).replace(tzinfo=None)
                    elif params.get("TZID"):
                        nv = nv.astimezone(v.tzinfo).replace(tzinfo=None)
                else:
                    nv = v + delta
                master.add(name, [nv], parameters=params)
    rrule = master.get("RRULE")
    if rrule is not None and rrule.get("UNTIL") and delta > dt.timedelta(0):
        until = rrule["UNTIL"][0]
        rrule["UNTIL"] = [until + delta]
    for ov in obj.overrides():
        rid_prop = ov.get("RECURRENCE-ID")
        rform = form_of(rid_prop)
        v = rid_prop.dt
        nv = (to_aware(v, local) + delta) if isinstance(v, dt.datetime) else v + delta
        write_dt(ov, "RECURRENCE-ID", nv, rform, local)


def set_partstat(comp: icalendar.cal.Component, me: Iterable[str], partstat: str) -> bool:
    mine = {address(a) for a in me}
    hit = False
    for a in attendee_props(comp):
        if address(a) in mine:
            a.params["PARTSTAT"] = partstat
            a.params.pop("RSVP", None)
            hit = True
    return hit


def strip_schedule_status(obj: EventObject) -> None:
    """SCHEDULE-STATUS is written by the server after it delivers. Removing it
    before a PUT makes whatever the server writes afterwards *this* write's result."""
    for c in obj.events():
        for p in ([c.get("ORGANIZER")] if c.get("ORGANIZER") is not None else []) + attendee_props(c):
            p.params.pop("SCHEDULE-STATUS", None)


def schedule_status(obj: EventObject) -> list[dict]:
    """What the server recorded about delivery, per recipient (deduplicated)."""
    seen: dict[tuple, dict] = {}
    for c in obj.events():
        org = c.get("ORGANIZER")
        props = ([("organizer", org)] if org is not None else []) + [("attendee", a) for a in attendee_props(c)]
        for kind, p in props:
            st = p.params.get("SCHEDULE-STATUS")
            if not st:
                continue
            code = str(st).split(";")[0].strip('"')
            key = (address(p), code)
            seen[key] = {"recipient": address(p), "as": kind, "status": code, "meaning": _STATUS_MEANING.get(code, "see RFC 6638 §3.2.9")}
    return list(seen.values())


_STATUS_MEANING = {
    "1.0": "not sent (the server judged the change insignificant)",
    "1.1": "sent by e-mail (iMIP)",
    "1.2": "delivered to the recipient's calendar on this server",
    "2.0": "delivered to the recipient's calendar on this server",
    "3.7": "invalid recipient",
    "3.8": "no scheduling privilege",
    "5.0": "delivery failed",
    "5.1": "delivery failed (could not be delivered)",
    "5.2": "delivery failed (invalid date)",
    "5.3": "delivery failed (no scheduling support for recipient)",
}


def schedule_agent_client(comp: icalendar.cal.Component, who: str) -> bool:
    """True if the ORGANIZER ('organizer') / every ATTENDEE ('attendees') carries SCHEDULE-AGENT=CLIENT."""
    if who == "organizer":
        org = comp.get("ORGANIZER")
        return org is not None and str(org.params.get("SCHEDULE-AGENT", "")).upper() == "CLIENT"
    atts = attendee_props(comp)
    return bool(atts) and all(str(a.params.get("SCHEDULE-AGENT", "")).upper() == "CLIENT" for a in atts)


def set_schedule_agent(obj: EventObject, who: str, client: bool) -> None:
    for c in obj.events():
        props = [c.get("ORGANIZER")] if who == "organizer" else attendee_props(c)
        for p in props:
            if p is None:
                continue
            if client:
                p.params["SCHEDULE-AGENT"] = "CLIENT"
            else:
                p.params.pop("SCHEDULE-AGENT", None)
