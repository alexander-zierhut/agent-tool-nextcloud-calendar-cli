"""Apply an invitation (iTIP REQUEST / CANCEL from an e-mail) to the calendar.

What Thunderbird does when you click "accept" on an update mail — minus the two
ways it broke on 05.11.26: the changed occurrence is written in the series' own
time form (no floating/TZID clash), and an EXDATE for it is dropped.
"""

from __future__ import annotations

import copy
import datetime as dt
import email
import email.policy
import re
import uuid
from pathlib import Path

import icalendar

from .diagnose import _forms_clash, align_override
from .errors import NotFoundError, ValidationError
from .ical import (
    EventObject,
    _form_params,
    convert,
    form_of,
    instant_key,
    make_override,
    remove_exdate,
    role_of,
    set_partstat,
)


def read_calendar_file(path: str) -> icalendar.Calendar:
    """An .ics file, or an e-mail (.eml) carrying a text/calendar part."""
    p = Path(path)
    if not p.exists():
        raise NotFoundError(f"no such file: {path}")
    raw = p.read_bytes()
    if raw.lstrip().upper().startswith(b"BEGIN:VCALENDAR"):
        return _parse(raw, path)
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    for part in msg.walk():
        if part.get_content_type() in ("text/calendar", "application/ics"):
            payload = part.get_payload(decode=True)
            if payload:
                return _parse(payload, path)
    raise ValidationError(f"{path} is neither an .ics file nor an e-mail with a text/calendar part.")


def _parse(raw: bytes, path: str) -> icalendar.Calendar:
    try:
        return icalendar.Calendar.from_ical(raw)
    except Exception as exc:
        raise ValidationError(f"{path}: not valid iCalendar: {exc}") from exc


def method_of(cal: icalendar.Calendar) -> str:
    return str(cal.get("METHOD", "PUBLISH")).upper()


def by_uid(cal: icalendar.Calendar) -> dict[str, list]:
    out: dict[str, list] = {}
    for c in cal.subcomponents:
        if c.name == "VEVENT" and c.get("UID"):
            out.setdefault(str(c.get("UID")), []).append(c)
    return out


def _timezones(cal: icalendar.Calendar) -> dict[str, object]:
    return {str(c.get("TZID")): c for c in cal.subcomponents if c.name == "VTIMEZONE"}


def object_name(uid: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9._@-]{1,200}", uid):
        return uid + ".ics"
    return f"{uuid.uuid4()}.ics"


def new_object(cal_slug: str, cal_href: str, cal_name: str, incoming: icalendar.Calendar, uid: str, comps: list) -> EventObject:
    out = icalendar.Calendar()
    out.add("PRODID", "-//agent-tool-nextcloud-calendar-cli//EN")
    out.add("VERSION", "2.0")
    used = {str(p.params.get("TZID")) for c in comps for p in _dt_props(c) if p.params.get("TZID")}
    for tzid, tz in _timezones(incoming).items():
        if tzid in used:
            out.add_component(copy.deepcopy(tz))
    for c in comps:
        out.add_component(copy.deepcopy(c))
    return EventObject(cal_slug, cal_href + object_name(uid), None, out, cal_name)


def _dt_props(comp) -> list:
    out = []
    for name in ("DTSTART", "DTEND", "RECURRENCE-ID"):
        if comp.get(name) is not None:
            out.append(comp.get(name))
    return out


def merge_request(existing: EventObject, incoming: icalendar.Calendar, comps: list, me, local: dt.tzinfo,
                  *, force: bool = False) -> tuple[EventObject, list[str]]:
    """Fold a REQUEST's components into a copy of *existing*. Returns (edited, notes)."""
    edited = existing.copy()
    notes: list[str] = []
    have_tz = _timezones(edited.cal)
    for tzid, tz in _timezones(incoming).items():
        if tzid not in have_tz:
            edited.cal.subcomponents.insert(0, copy.deepcopy(tz))
    old_master = existing.master()
    my_master_status = role_of(old_master, me).my_status if old_master is not None else None
    for comp in comps:
        comp = copy.deepcopy(comp)
        rid = comp.get("RECURRENCE-ID")
        seq_in = int(comp.get("SEQUENCE", 0) or 0)
        if rid is None:
            cur = edited.master()
            seq_cur = int(cur.get("SEQUENCE", 0) or 0) if cur is not None else -1
            if cur is not None and seq_in < seq_cur and not force:
                notes.append(f"skipped the series update: it is older (SEQUENCE {seq_in}) than the stored one ({seq_cur}). --force applies it anyway.")
                continue
            if cur is not None:
                _carry_over(cur, comp, me)
                old_ex = [v for v in existing.exdate_values()]
                edited.cal.subcomponents.remove(cur)
                edited.cal.add_component(comp)
                in_keys = {instant_key(v.dt, local) for v in edited.exdate_values()}
                mform = form_of(comp.get("DTSTART"))
                for v in old_ex:
                    if instant_key(v.dt, local) not in in_keys:
                        comp.add("EXDATE", [convert(v.dt, mform, local)], parameters=_form_params(mform))
                notes.append("updated the series.")
            else:
                edited.cal.add_component(comp)
                notes.append("added the series.")
            continue
        cur = edited.find_component(rid, local)
        seq_cur = int(cur.get("SEQUENCE", 0) or 0) if cur is not None else -1
        if cur is not None and seq_in < seq_cur and not force:
            notes.append(f"skipped the change of {rid.dt}: older than the stored one.")
            continue
        base = cur if cur is not None else edited.master()
        if base is not None:
            _carry_over(base, comp, me, fallback_status=my_master_status)
        if cur is not None:
            edited.cal.subcomponents.remove(cur)
        edited.cal.add_component(comp)
        if edited.master() is not None:
            if _forms_clash(form_of(edited.master().get("DTSTART")), form_of(comp.get("RECURRENCE-ID"))):
                align_override(edited, comp, local)
                notes.append(f"wrote the changed occurrence {rid.dt} in the series' time form (prevents the duplicate).")
            if remove_exdate(edited, comp.get("RECURRENCE-ID"), local):
                notes.append(f"removed the exclusion of {rid.dt} (prevents the vanished occurrence).")
        notes.append(f"{'updated' if cur is not None else 'added'} the changed occurrence {rid.dt}.")
    return edited, notes


def _carry_over(old, new, me, fallback_status: str | None = None) -> None:
    """Keep what is mine across an organizer's update: my answer and my alarms."""
    status = role_of(old, me).my_status or fallback_status
    if status and status != "NEEDS-ACTION":
        set_partstat(new, me, status)
    if not any(s.name == "VALARM" for s in new.subcomponents):
        for s in old.subcomponents:
            if s.name == "VALARM":
                new.add_component(copy.deepcopy(s))
    org_old, org_new = old.get("ORGANIZER"), new.get("ORGANIZER")
    if org_old is not None and org_new is not None and org_old.params.get("SCHEDULE-AGENT"):
        org_new.params["SCHEDULE-AGENT"] = org_old.params["SCHEDULE-AGENT"]


def apply_cancel(existing: EventObject, comps: list, local: dt.tzinfo) -> tuple[EventObject, list[str]]:
    """Mark the cancelled occurrence(s) — or the whole event — STATUS:CANCELLED."""
    edited = existing.copy()
    notes = []
    whole = any(c.get("RECURRENCE-ID") is None for c in comps)
    if whole:
        for c in edited.events():
            c.pop("STATUS", None)
            c.add("STATUS", "CANCELLED")
        notes.append("marked the whole event as cancelled.")
        return edited, notes
    for c in comps:
        rid = c.get("RECURRENCE-ID")
        ov = edited.find_component(rid, local) or make_override(edited, rid, local)
        ov.pop("STATUS", None)
        ov.add("STATUS", "CANCELLED")
        notes.append(f"marked the occurrence {rid.dt} as cancelled.")
    return edited, notes
