"""Turning what the caller typed into exactly one event (and one occurrence).

Refuse rather than guess: a title that matches two meetings is an error listing
both, never "the first one". Moving the wrong meeting costs more than a retry.
"""

from __future__ import annotations

import datetime as dt

from .dav import Dav
from .errors import NotFoundError, ValidationError
from .ical import EventObject, instant_key, to_aware
from .timeparse import fmt, parse_when

_WINDOW_BEFORE = dt.timedelta(days=31)
_WINDOW_AFTER = dt.timedelta(days=400)


def find_objects(dav: Dav, ref: str, *, calendar: str | None, local: dt.tzinfo,
                 around: dt.date | None = None) -> list[EventObject]:
    ref = ref.strip()
    cals = [dav.calendar(calendar)] if calendar else dav.calendars()
    if "/" in ref and ref.lower().endswith(".ics"):
        slug, name = ref.rsplit("/", 1)
        cal = dav.calendar(slug)
        return [dav.get(cal, name)]
    if " " not in ref:
        hits = dav.objects_by_uid(ref, cals)
        if hits:
            return hits
    now = dt.datetime.now(local)
    start, end = now - _WINDOW_BEFORE, now + _WINDOW_AFTER
    if around is not None:
        a = dt.datetime.combine(around, dt.time(), tzinfo=local)
        start, end = min(start, a - dt.timedelta(days=2)), max(end, a + dt.timedelta(days=2))
    needle = ref.lower()
    found: dict[str, EventObject] = {}
    for cal in cals:
        for obj in dav.objects_between(cal, start, end):
            if any(needle in str(c.get("SUMMARY", "")).lower() for c in obj.events()):
                found.setdefault(obj.href, obj)
    exact = [o for o in found.values() if any(str(c.get("SUMMARY", "")).strip().lower() == needle for c in o.events())]
    return exact if len(exact) == 1 else list(found.values())


def resolve_one(dav: Dav, ref: str, *, calendar: str | None, local: dt.tzinfo, around: dt.date | None = None) -> EventObject:
    hits = find_objects(dav, ref, calendar=calendar, local=local, around=around)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise NotFoundError(
            f"no event matching '{ref}' (searched titles from 31 days ago to ~13 months ahead"
            f"{' in ' + calendar if calendar else ' in all calendars'}). "
            "Use `nextcloud-calendar event list --search TEXT` to find it, then pass its id."
        )
    now = dt.datetime.now(local)
    cands = []
    for o in hits:
        nxt = o.occurrences(now - dt.timedelta(days=31), now + dt.timedelta(days=400), local)
        m = o.master() or o.events()[0]
        cands.append({"id": o.id, "summary": str(m.get("SUMMARY", "")), "next": fmt(nxt[0].start) if nxt else None})
    raise ValidationError(
        f"'{ref}' matches {len(hits)} events; pass one of these ids instead: "
        + "; ".join(f"{c['id']} ({c['summary']}, {c['next']})" for c in cands[:15]),
        detail={"candidates": cands[:25]},
    )


def pick_occurrence(obj: EventObject, when: str | None, local: dt.tzinfo, *, series: bool) -> dt.date | dt.datetime | None:
    """The RECURRENCE-ID (as a python value) of the occurrence the caller means,
    or None for "the whole event". A recurring event needs --occurrence or --series."""
    if not obj.is_recurring():
        if when:
            # Tolerated: naming the date of a one-off event is just a confirmation.
            return None
        return None
    if series:
        if when:
            raise ValidationError("pass either --occurrence or --series, not both.")
        return None
    if not when:
        raise ValidationError(
            f"'{obj.id}' is a recurring event. Pass --occurrence DATE for one occurrence, or --series for all of them."
        )
    target = parse_when(when, local)
    day = target.astimezone(local).date() if isinstance(target, dt.datetime) else target
    lo = dt.datetime.combine(day, dt.time(), tzinfo=local) - dt.timedelta(days=1)
    occs = obj.occurrences(lo, lo + dt.timedelta(days=3), local)

    def local_day(v):
        return v.astimezone(local).date() if isinstance(v, dt.datetime) else v

    cands = [o for o in occs if o.recurrence_id is not None and (local_day(o.recurrence_id) == day or local_day(o.start) == day)]
    if isinstance(target, dt.datetime) and len(cands) > 1:
        key = instant_key(target, local)
        exact = [o for o in cands if instant_key(o.recurrence_id, local) == key or instant_key(o.start, local) == key]
        cands = exact or cands
    uniq = {instant_key(o.recurrence_id, local): o for o in cands}
    if len(uniq) == 1:
        return next(iter(uniq.values())).recurrence_id
    if not uniq:
        near = obj.occurrences(lo - dt.timedelta(days=14), lo + dt.timedelta(days=17), local)
        raise NotFoundError(
            f"'{obj.id}' has no occurrence on {day.isoformat()}. Nearby: "
            + (", ".join(fmt(o.start) for o in near[:10]) or "none"),
        )
    raise ValidationError(
        f"'{obj.id}' has {len(uniq)} occurrences on {day.isoformat()}; add the time, e.g. --occurrence '{day} "
        f"{to_aware(next(iter(uniq.values())).start, local).strftime('%H:%M') if isinstance(next(iter(uniq.values())).start, dt.datetime) else ''}'."
    )
