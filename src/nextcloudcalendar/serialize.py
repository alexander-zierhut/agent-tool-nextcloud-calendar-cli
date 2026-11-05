"""The CLI's output contract: one pure function per shape, hand-listed keys."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from .ical import EventObject, Occurrence, address, attendee_props, form_of, role_of
from .timeparse import fmt


def _text(comp, name: str) -> str | None:
    v = comp.get(name)
    return str(v) if v is not None and str(v) != "" else None


def occurrence(o: Occurrence, me: Iterable[str], local: dt.tzinfo) -> dict:
    """One row of `event list`: what happens when, and what it means for me."""
    comp = o.comp
    role = role_of(comp, me)
    start = o.start.astimezone(local) if isinstance(o.start, dt.datetime) else o.start
    end = o.end.astimezone(local) if isinstance(o.end, dt.datetime) else o.end
    rid = o.recurrence_id
    if isinstance(rid, dt.datetime):
        rid = rid.astimezone(local)
    return {
        "id": o.obj.id,
        "occurrence": fmt(rid) if rid is not None else None,
        "summary": _text(comp, "SUMMARY"),
        "start": fmt(start),
        "end": fmt(end),
        "allDay": o.all_day,
        "calendar": o.obj.calendar,
        "location": _text(comp, "LOCATION"),
        "status": (_text(comp, "STATUS") or "CONFIRMED").upper(),
        "role": role.kind,
        "myStatus": role.my_status,
        "organizer": role.organizer if role.kind == "attendee" else None,
        "attendees": len(attendee_props(comp)),
        "recurring": o.obj.is_recurring(),
        "uid": o.obj.uid,
    }


def event(obj: EventObject, me: Iterable[str], local: dt.tzinfo, *, upcoming: list[Occurrence] | None = None) -> dict:
    """`event get`: the whole object — series rule, exceptions, people."""
    master = obj.master()
    base = master if master is not None else (obj.events()[0] if obj.events() else None)
    if base is None:
        return {"id": obj.id, "uid": obj.uid, "error": "no VEVENT in this object"}
    role = role_of(base, me)
    start = base.get("DTSTART")
    out = {
        "id": obj.id,
        "uid": obj.uid,
        "calendar": obj.calendar,
        "summary": _text(base, "SUMMARY"),
        "location": _text(base, "LOCATION"),
        "description": _text(base, "DESCRIPTION"),
        "status": (_text(base, "STATUS") or "CONFIRMED").upper(),
        "start": fmt(start.dt) if start is not None else None,
        "timeForm": form_of(start).describe() if start is not None else None,
        "end": fmt(base.get("DTEND").dt) if base.get("DTEND") is not None else None,
        "duration": str(base.get("DURATION").dt) if base.get("DURATION") is not None else None,
        "role": role.kind,
        "myStatus": role.my_status,
        "organizer": address(base.get("ORGANIZER")) if base.get("ORGANIZER") is not None else None,
        "attendees": [
            {
                "address": address(a),
                "name": str(a.params.get("CN")) if a.params.get("CN") else None,
                "status": str(a.params.get("PARTSTAT", "NEEDS-ACTION")).upper(),
                "role": str(a.params.get("ROLE", "REQ-PARTICIPANT")).upper(),
            }
            for a in attendee_props(base)
        ],
        "serverScheduling": "off (SCHEDULE-AGENT=CLIENT)" if base.get("ORGANIZER") is not None
        and str(base.get("ORGANIZER").params.get("SCHEDULE-AGENT", "")).upper() == "CLIENT" else "on",
        "sequence": int(base.get("SEQUENCE", 0) or 0),
        "recurring": obj.is_recurring(),
    }
    if master is not None and master.get("RRULE") is not None:
        out["rrule"] = master.get("RRULE").to_ical().decode()
        out["excluded"] = [fmt(v.dt) for v in obj.exdate_values()]
    ovs = obj.overrides()
    if ovs:
        out["changedOccurrences"] = [
            {
                "occurrence": fmt(c.get("RECURRENCE-ID").dt),
                "occurrenceForm": form_of(c.get("RECURRENCE-ID")).describe(),
                "start": fmt(c.get("DTSTART").dt) if c.get("DTSTART") is not None else None,
                "end": fmt(c.get("DTEND").dt) if c.get("DTEND") is not None else None,
                "status": (_text(c, "STATUS") or "CONFIRMED").upper(),
                "summary": _text(c, "SUMMARY"),
            }
            for c in ovs
        ]
    if upcoming is not None:
        out["next"] = [occurrence(o, me, local) for o in upcoming]
    return out
