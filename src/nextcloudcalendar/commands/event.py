"""Events: list, read, create, move, update, respond, cancel, delete, import.

Every write is QUIET by default — only your calendar changes, nobody is e-mailed —
and reports what the server actually did (`mailed`, `scheduling`). Pass
--notify to let the server mail the other people. See `guide scheduling`.
"""

from __future__ import annotations

import datetime as dt
import uuid

import icalendar
import typer

from .. import serialize
from ..errors import AuthError, SchedulingRefused, ValidationError
from ..ical import (
    EventObject,
    add_exdate,
    duration_of,
    instant_key,
    make_override,
    set_partstat,
    set_times,
    shift_series,
    to_aware,
)
from ..resolve import pick_occurrence, resolve_one
from ..timeparse import fmt, parse_date, parse_duration, parse_when, today
from ._shared import CALENDAR_OPT_HELP, NOTIFY_HELP, ctx_obj

app = typer.Typer(no_args_is_help=True)

def _when(row: dict) -> str:
    """Compact human time span: 'Thu 05.11. 13:00-14:15', 'Fri 06.11.' (all day),
    '01.10.26-22.02.27' (multi-day). The year is shown whenever it is not the
    current one. All-day ends are exclusive in iCalendar."""
    try:
        s = dt.datetime.fromisoformat(row["start"]) if "T" in row["start"] else dt.date.fromisoformat(row["start"])
        e_raw = row.get("end")
        e = (dt.datetime.fromisoformat(e_raw) if "T" in e_raw else dt.date.fromisoformat(e_raw)) if e_raw else None
    except (KeyError, TypeError, ValueError):
        return f"{row.get('start')} - {row.get('end')}"
    this_year = dt.date.today().year

    def day(d) -> str:
        return d.strftime("%a %d.%m.") if d.year == this_year else d.strftime("%a %d.%m.%y")

    if not isinstance(s, dt.datetime):
        last = (e - dt.timedelta(days=1)) if isinstance(e, dt.date) and e > s else s
        if last == s:
            return day(s)
        return f"{s:%d.%m.%y}-{last:%d.%m.%y}"
    head = f"{day(s)} {s:%H:%M}"
    if e is None:
        return head
    if isinstance(e, dt.datetime) and e.date() == s.date():
        return f"{head}-{e:%H:%M}"
    return f"{head}-{day(e)} {e:%H:%M}" if isinstance(e, dt.datetime) else head


def _who(row: dict) -> str:
    """'' for personal events, 'organizer', or my answer as an attendee."""
    if row.get("role") == "personal":
        return ""
    if row.get("role") == "organizer":
        return "organizer"
    return (row.get("myStatus") or "invited").lower()


# Table mode is for humans: compact columns. Agents read the JSON (id, occurrence, ...).
_COLUMNS = [
    ("When", _when), ("Summary", "summary"), ("Me", _who),
    ("Status", lambda r: "" if r.get("status") == "CONFIRMED" else (r.get("status") or "").lower()),
    ("Calendar", "calendar"),
]

REF_HELP = "The event: an id from `event list` (calendar/file.ics), its UID, or (part of) its title."
OCC_HELP = "Which occurrence of a recurring event: a date (2026-11-06, 06.11.2026, fri, tomorrow) or date+time."
SERIES_HELP = "Apply to every occurrence of a recurring event."


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load(obj, ref: str, calendar: str | None, occurrence: str | None, series: bool):
    local = obj.local
    around = None
    if occurrence:
        w = parse_when(occurrence, local)
        around = w.astimezone(local).date() if isinstance(w, dt.datetime) else w
    dav = obj.dav()
    eo = resolve_one(dav, ref, calendar=calendar, local=local, around=around)
    _require_writable(dav, eo.calendar)
    rid = pick_occurrence(eo, occurrence, local, series=series)
    return eo, rid


def _require_writable(dav, calendar_ref) -> None:
    """Refuse before building a write (also under --dry-run), the way the server
    would (403 -> exit 4), instead of previewing a PUT that can never succeed."""
    cal = dav.calendar(calendar_ref)
    if not cal.writable:
        raise AuthError(f"calendar '{cal.slug}' is read-only for you; this event cannot be changed here.")


def _target(edited: EventObject, rid, local, *, create: bool = True):
    if rid is None:
        return edited.master() or edited.events()[0]
    comp = edited.find_component(rid, local)
    if comp is None and create:
        comp = make_override(edited, rid, local)
    return comp


def _times(comp, local):
    s = comp.get("DTSTART").dt
    start = to_aware(s, local) if isinstance(s, dt.datetime) else s
    return start, start + duration_of(comp)


def _affected(obj: EventObject, rid, local, me, near=None) -> dict | None:
    """The occurrence row after the write, for the caller to confirm."""
    if obj is None:
        return None
    if rid is not None:
        key = instant_key(rid, local)
        anchor = to_aware(rid, local) if isinstance(rid, dt.datetime) else dt.datetime.combine(rid, dt.time(), tzinfo=local)
        lo = anchor - dt.timedelta(days=60)
        for o in obj.occurrences(lo, anchor + dt.timedelta(days=60), local):
            if o.recurrence_id is not None and instant_key(o.recurrence_id, local) == key:
                return serialize.occurrence(o, me, local)
        return None
    now = dt.datetime.now(local)
    if near is not None:
        a = near if isinstance(near, dt.datetime) else dt.datetime.combine(near, dt.time(), tzinfo=local)
        occ = obj.occurrences(a - dt.timedelta(days=1), a + dt.timedelta(days=2), local)
    else:
        occ = obj.occurrences(now - dt.timedelta(days=1), now + dt.timedelta(days=400), local)
    return serialize.occurrence(occ[0], me, local) if occ else None


def _emit(obj, rep, rid=None, near=None) -> None:
    out = rep.to_dict()
    if rep.obj is not None and not rep.deleted:
        out["event"] = _affected(rep.obj, rid, obj.local, obj.me(), near=near)
    obj.emitter.emit(out)


def _new_start(text: str, current, local):
    """--to / --start: a full date-time, a time on the occurrence's day, or a date (all-day)."""
    on = current.astimezone(local).date() if isinstance(current, dt.datetime) else current
    value = parse_when(text, local, on=on)
    if isinstance(current, dt.datetime) and not isinstance(value, dt.datetime):
        raise ValidationError(f"'{text}' is a date, but this event has a time. Give a time too, e.g. '{value} 11:30'.")
    if not isinstance(current, dt.datetime) and isinstance(value, dt.datetime):
        raise ValidationError(f"this is an all-day event; '{text}' has a time. Give a date instead, e.g. '{value.date()}'.")
    return value


def _shift(by: str, current) -> dt.timedelta:
    """--by: any duration for timed events, whole days only for all-day ones."""
    delta = parse_duration(by)
    if not isinstance(current, dt.datetime) and delta % dt.timedelta(days=1):
        raise ValidationError(f"this is an all-day event; --by must be whole days (e.g. +1d), not '{by}'.")
    return delta


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

@app.command("list")
def list_(
    ctx: typer.Context,
    start: str = typer.Option(None, "--from", help="First day (default: today). Accepts 2026-11-06, 06.11., today, mon, +3d."),
    end: str = typer.Option(None, "--to", help="Last day, inclusive (default: --from + --days - 1)."),
    days: int = typer.Option(7, "--days", help="Window length when --to is not given."),
    calendar: str = typer.Option(None, "--calendar", help=CALENDAR_OPT_HELP),
    search: str = typer.Option(None, "--search", help="Only events whose title/location/description contains this text."),
    limit: int = typer.Option(500, "--limit", help="At most this many occurrences."),
) -> None:
    """List occurrences in a time window, recurring events expanded, sorted by start.

    Example: `nextcloud-calendar event list --from mon --days 5`
    Each row's `id` (+ `occurrence` for recurring events) is what the other
    commands take. Times are in your zone (`auth status` shows it).
    """
    obj = ctx_obj(ctx)
    local = obj.local
    first = parse_date(start, local) if start else today(local)
    if not end and days < 1:
        raise ValidationError(f"--days must be at least 1, got {days}.")
    last = parse_date(end, local) if end else first + dt.timedelta(days=days - 1)
    if last < first:
        raise ValidationError("--to is before --from.")
    lo = dt.datetime.combine(first, dt.time(), tzinfo=local)
    hi = dt.datetime.combine(last + dt.timedelta(days=1), dt.time(), tzinfo=local)
    dav = obj.dav()
    cals = [dav.calendar(calendar)] if calendar else dav.calendars()
    me = obj.me()
    needle = search.lower() if search else None
    rows = []
    for cal in cals:
        for eo in dav.objects_between(cal, lo, hi):
            for o in eo.occurrences(lo, hi, local):
                if needle:
                    hay = " ".join(str(o.comp.get(k, "")) for k in ("SUMMARY", "LOCATION", "DESCRIPTION")).lower()
                    if needle not in hay:
                        continue
                rows.append(serialize.occurrence(o, me, local))
    rows.sort(key=lambda r: (r["start"] if "T" in (r["start"] or "") else (r["start"] or "") + "T00:00", r["summary"] or ""))
    if obj.emitter.stream:
        obj.emitter.stream_json(rows[:limit])
        return
    obj.emitter.emit(rows[:limit], columns=_COLUMNS)


@app.command("get")
def get(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help=REF_HELP),
    calendar: str = typer.Option(None, "--calendar", help=CALENDAR_OPT_HELP),
    ics: bool = typer.Option(False, "--ics", help="Return the raw iCalendar text instead."),
    upcoming: int = typer.Option(5, "--upcoming", help="How many next occurrences to include."),
) -> None:
    """Show one event: times, series rule, changed/excluded occurrences, people.

    Example: `nextcloud-calendar event get "Team Weekly"`
    `serverScheduling: off` means the server never mails anyone about it
    (typical for invites Thunderbird received by e-mail).
    """
    obj = ctx_obj(ctx)
    eo = resolve_one(obj.dav(), ref, calendar=calendar, local=obj.local)
    if ics:
        obj.emitter.emit({"id": eo.id, "etag": eo.etag, "href": eo.href, "ics": eo.to_ical()})
        return
    now = dt.datetime.now(obj.local)
    nxt = eo.occurrences(now, now + dt.timedelta(days=400), obj.local)[:upcoming]
    obj.emitter.emit(serialize.event(eo, obj.me(), obj.local, upcoming=nxt))


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------

@app.command("create")
def create(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title", help="What it is."),
    start: str = typer.Option(..., "--start", help="'2026-11-06 11:30', 'tomorrow 9:00', 'fri 14:00', or a date for all-day."),
    end: str = typer.Option(None, "--end", help="End time or date-time (default: start + --duration)."),
    duration: str = typer.Option(None, "--duration", help="e.g. 30m, 1h30m, 2.5h (default 1h; all-day: 1d)."),
    calendar: str = typer.Option(None, "--calendar", help=CALENDAR_OPT_HELP),
    location: str = typer.Option(None, "--location"),
    description: str = typer.Option(None, "--description"),
    attendee: list[str] = typer.Option(None, "--attendee", help="E-mail of someone to invite (repeatable). Invited only with --notify."),
    notify: bool = typer.Option(False, "--notify", help="Send invitations to the --attendee addresses."),
) -> None:
    """Create an event in your default (or the given) calendar.

    Example: `nextcloud-calendar event create --title "Zahnarzt" --start "2026-11-12 08:30" --duration 45m`
    With --attendee but without --notify the people are recorded, not invited.
    """
    obj = ctx_obj(ctx)
    local = obj.local
    s = parse_when(start, local)
    if end:
        e = parse_when(end, local, on=s.date() if isinstance(s, dt.datetime) else s)
    elif isinstance(s, dt.datetime):
        e = s + parse_duration(duration or "1h")
    else:
        e = s + (parse_duration(duration) if duration else dt.timedelta(days=1))
        if isinstance(e, dt.datetime):
            e = e.date()
    if type(s) is not type(e):
        raise ValidationError("--start and --end must both be dates (all-day) or both date-times.")
    if e <= s:
        raise ValidationError("the event must end after it starts.")
    dav = obj.dav()
    cal = dav.calendar(calendar or obj.profile().default_calendar)
    if not cal.writable:
        raise AuthError(f"calendar '{cal.slug}' is read-only for you.")
    uid = str(uuid.uuid4())
    ev = icalendar.Event()
    ev.add("UID", uid)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    ev.add("DTSTAMP", now)
    ev.add("CREATED", now)
    ev.add("SUMMARY", title)
    ev.add("DTSTART", s)
    ev.add("DTEND", e)
    ev.add("SEQUENCE", 0)
    if location:
        ev.add("LOCATION", location)
    if description:
        ev.add("DESCRIPTION", description)
    if attendee:
        me = obj.me()
        if not me:
            raise ValidationError("your e-mail address is unknown; add it with `auth login --address you@example.com`.")
        ev.add("ORGANIZER", f"mailto:{me[0]}", parameters={"CN": dav.principal().get("displayName") or me[0]})
        ev.add("ATTENDEE", f"mailto:{me[0]}", parameters={"PARTSTAT": "ACCEPTED", "ROLE": "CHAIR"})
        for a in attendee:
            ev.add("ATTENDEE", f"mailto:{a.strip()}", parameters={"PARTSTAT": "NEEDS-ACTION", "RSVP": "TRUE", "ROLE": "REQ-PARTICIPANT"})
    c = icalendar.Calendar()
    c.add("PRODID", "-//agent-tool-nextcloud-calendar-cli//EN")
    c.add("VERSION", "2.0")
    c.add_component(ev)
    try:
        c.add_missing_timezones()
    except Exception:
        pass
    new = EventObject(cal.slug, cal.href + uid + ".ics", None, c, cal.name)
    rep = obj.writer().save(None, new, notify=notify, action="create")
    _emit(obj, rep, near=s)


@app.command("move")
def move(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help=REF_HELP),
    to: str = typer.Option(None, "--to", help="New start: '11:30' (same day), '2026-11-07 09:00', 'tomorrow 10:00'. Duration is kept."),
    by: str = typer.Option(None, "--by", help="Shift by a duration: +30m, -1h, +1d."),
    occurrence: str = typer.Option(None, "--occurrence", help=OCC_HELP),
    series: bool = typer.Option(False, "--series", help=SERIES_HELP),
    calendar: str = typer.Option(None, "--calendar", help=CALENDAR_OPT_HELP),
    notify: bool = typer.Option(False, "--notify", help=NOTIFY_HELP),
) -> None:
    """Move an event (or one occurrence, or a whole series), keeping its length.

    Example: `nextcloud-calendar event move "Team Weekly" --occurrence 2026-11-06 --to 11:30`
    Quiet by default. For a meeting someone else organises this only changes
    YOUR calendar — the server cannot propose a new time to the organizer.
    """
    if bool(to) == bool(by):
        raise ValidationError("pass exactly one of --to or --by.")
    obj = ctx_obj(ctx)
    local = obj.local
    eo, rid = _load(obj, ref, calendar, occurrence, series)
    edited = eo.copy()
    if rid is None and eo.is_recurring():
        master = edited.master()
        s, _ = _times(master, local)
        delta = _shift(by, s) if by else _new_start(to, s, local) - s
        shift_series(edited, delta, local)
        rep = obj.writer().save(eo, edited, notify=notify, action="move")
        _emit(obj, rep)
        return
    comp = _target(edited, rid, local)
    s, e = _times(comp, local)
    new_s = s + _shift(by, s) if by else _new_start(to, s, local)
    set_times(comp, new_s, new_s + (e - s), local)
    rep = obj.writer().save(eo, edited, notify=notify, action="move")
    _emit(obj, rep, rid=rid, near=new_s)


@app.command("update")
def update(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help=REF_HELP),
    start: str = typer.Option(None, "--start", help="New start (keeps the length unless --end/--duration given)."),
    end: str = typer.Option(None, "--end", help="New end: '13:30' (same day) or a full date-time."),
    duration: str = typer.Option(None, "--duration", help="New length, e.g. 2h30m."),
    extend: str = typer.Option(None, "--extend", help="Lengthen (or with '-', shorten) the end, e.g. +1h."),
    title: str = typer.Option(None, "--title"),
    location: str = typer.Option(None, "--location"),
    description: str = typer.Option(None, "--description"),
    occurrence: str = typer.Option(None, "--occurrence", help=OCC_HELP),
    series: bool = typer.Option(False, "--series", help=SERIES_HELP),
    calendar: str = typer.Option(None, "--calendar", help=CALENDAR_OPT_HELP),
    notify: bool = typer.Option(False, "--notify", help=NOTIFY_HELP),
) -> None:
    """Change times, length, title, location or description.

    Example: `nextcloud-calendar event update "Workshop" --occurrence 2026-11-12 --duration 2h30m`
    Quiet by default (only your calendar). --series changes every occurrence.
    """
    if not any((start, end, duration, extend, title, location, description)):
        raise ValidationError("nothing to change. Pass --start, --end, --duration, --extend, --title, --location or --description.")
    if sum(bool(x) for x in (end, duration, extend)) > 1:
        raise ValidationError("pass only one of --end, --duration, --extend.")
    obj = ctx_obj(ctx)
    local = obj.local
    eo, rid = _load(obj, ref, calendar, occurrence, series)
    edited = eo.copy()
    whole_series = rid is None and eo.is_recurring()
    comp = _target(edited, rid, local)
    s, e = _times(comp, local)
    new_s = _new_start(start, s, local) if start else s
    if end:
        new_e = parse_when(end, local, on=new_s.date() if isinstance(new_s, dt.datetime) else new_s)
    elif duration:
        new_e = new_s + parse_duration(duration)
    elif extend:
        new_e = (new_s + (e - s)) + parse_duration(extend)
    else:
        new_e = new_s + (e - s)
    if type(new_e) is not type(new_s):
        raise ValidationError("start and end must both be dates (all-day) or both date-times; "
                              "an all-day event takes a date for --end and whole days for --duration/--extend.")
    if not isinstance(new_s, dt.datetime) and (new_e - new_s) % dt.timedelta(days=1):
        raise ValidationError("an all-day event lasts whole days; use e.g. --duration 2d.")
    if new_e <= new_s:
        raise ValidationError("the event must end after it starts.")
    if (new_s, new_e) != (s, e):
        if whole_series and new_s != s:
            shift_series(edited, new_s - s, local)
            comp = edited.master()
        set_times(comp, new_s, new_e, local)
    targets = [comp]
    if whole_series:
        targets += edited.overrides()
    for name, value in (("SUMMARY", title), ("LOCATION", location), ("DESCRIPTION", description)):
        if value is None:
            continue
        old = str(comp.get(name, ""))
        for t in targets:
            if t is comp or str(t.get(name, "")) == old:
                t.pop(name, None)
                if value != "":
                    t.add(name, value)
    rep = obj.writer().save(eo, edited, notify=notify, action="update")
    _emit(obj, rep, rid=rid, near=None if whole_series else new_s)


@app.command("respond")
def respond(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help=REF_HELP),
    answer: str = typer.Argument(..., help="accepted | declined | tentative"),
    occurrence: str = typer.Option(None, "--occurrence", help=OCC_HELP),
    series: bool = typer.Option(False, "--series", help=SERIES_HELP),
    calendar: str = typer.Option(None, "--calendar", help=CALENDAR_OPT_HELP),
    notify: bool = typer.Option(False, "--notify", help="Send your answer to the organizer (server e-mails a REPLY; verified)."),
) -> None:
    """Answer an invitation: accepted, declined or tentative.

    Example: `nextcloud-calendar event respond "Jour fixe" declined --occurrence 2026-11-20 --notify`
    Without --notify only your calendar records the answer.
    """
    status = {"accepted": "ACCEPTED", "accept": "ACCEPTED", "declined": "DECLINED", "decline": "DECLINED",
              "tentative": "TENTATIVE", "maybe": "TENTATIVE"}.get(answer.strip().lower())
    if status is None:
        raise ValidationError("answer must be accepted, declined or tentative.")
    obj = ctx_obj(ctx)
    local = obj.local
    eo, rid = _load(obj, ref, calendar, occurrence, series)
    role = obj.writer().role(eo)
    if role.kind != "attendee":
        raise ValidationError(f"you are not an invited attendee of '{eo.id}' (role: {role.kind}); there is nothing to answer.")
    edited = eo.copy()
    me = obj.me()
    comps = [_target(edited, rid, local)] if rid is not None else edited.events()
    if not any(set_partstat(c, me, status) for c in comps):
        raise ValidationError(f"none of your addresses ({', '.join(me)}) is on the attendee list; add yours with `auth login --address`.")
    rep = obj.writer().save(eo, edited, notify=notify, action="respond", attendee_notify_ok=True)
    _emit(obj, rep, rid=rid)


@app.command("cancel")
def cancel(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help=REF_HELP),
    occurrence: str = typer.Option(None, "--occurrence", help=OCC_HELP),
    series: bool = typer.Option(False, "--series", help=SERIES_HELP),
    calendar: str = typer.Option(None, "--calendar", help=CALENDAR_OPT_HELP),
    notify: bool = typer.Option(False, "--notify", help="You organise it: mail the cancellation to every attendee."),
) -> None:
    """Mark an event (or one occurrence) as cancelled; it stays visible, struck through.

    Example: `nextcloud-calendar event cancel "Team-Lunch" --occurrence fri`
    Use `event delete` to remove it instead, `event respond ... declined` to
    say you will not attend someone else's meeting.
    """
    obj = ctx_obj(ctx)
    local = obj.local
    eo, rid = _load(obj, ref, calendar, occurrence, series)
    if notify and obj.writer().role(eo).kind == "attendee":
        raise SchedulingRefused(
            "only the organizer can cancel a meeting for everyone. To tell the organizer you will not come: "
            "`event respond <ref> declined --notify`. Without --notify the event is marked cancelled in your calendar only."
        )
    edited = eo.copy()
    comps = [_target(edited, rid, local)] if rid is not None else edited.events()
    for c in comps:
        c.pop("STATUS", None)
        c.add("STATUS", "CANCELLED")
    rep = obj.writer().save(eo, edited, notify=notify, action="cancel")
    _emit(obj, rep, rid=rid)


@app.command("delete")
def delete(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help=REF_HELP),
    occurrence: str = typer.Option(None, "--occurrence", help=OCC_HELP),
    series: bool = typer.Option(False, "--series", help=SERIES_HELP),
    calendar: str = typer.Option(None, "--calendar", help=CALENDAR_OPT_HELP),
    notify: bool = typer.Option(False, "--notify", help="Organizer: mail a cancellation. Attendee: decline to the organizer first."),
) -> None:
    """Delete an event, or remove one occurrence from a series.

    Example: `nextcloud-calendar event delete "Zahnarzt"`
    Deleted events go to the trash (`trash list` / `trash restore`).
    """
    obj = ctx_obj(ctx)
    local = obj.local
    eo, rid = _load(obj, ref, calendar, occurrence, series)
    writer = obj.writer()
    if rid is None:
        rep = writer.delete(eo, notify=notify)
        _emit(obj, rep)
        return
    if notify and writer.role(eo).kind == "attendee":
        raise SchedulingRefused(
            "to tell the organizer you skip one occurrence, decline it: "
            "`event respond <ref> declined --occurrence DATE --notify`. Without --notify the occurrence is removed "
            "from your calendar only."
        )
    edited = eo.copy()
    if edited.master() is None:
        # Only this occurrence is stored (you were invited to one occurrence) -> the object IS the occurrence.
        rep = writer.delete(eo, notify=notify)
        _emit(obj, rep)
        return
    add_exdate(edited, rid, local)
    rep = writer.save(eo, edited, notify=notify, action="delete-occurrence")
    out = rep.to_dict()
    out["removedOccurrence"] = fmt(rid.astimezone(local) if isinstance(rid, dt.datetime) else rid)
    obj.emitter.emit(out)


@app.command("import")
def import_(
    ctx: typer.Context,
    file: str = typer.Argument(..., help="An .ics file or a saved e-mail (.eml) with an invitation."),
    calendar: str = typer.Option(None, "--calendar", help="Calendar for NEW events (default: your default calendar)."),
    accept: bool = typer.Option(False, "--accept", help="Mark yourself as accepted."),
    decline: bool = typer.Option(False, "--decline", help="Mark yourself as declined."),
    tentative: bool = typer.Option(False, "--tentative", help="Mark yourself as tentative."),
    force: bool = typer.Option(False, "--force", help="Apply even if the invitation is older than what is stored."),
    notify: bool = typer.Option(False, "--notify", help="Send your answer to the organizer."),
) -> None:
    """Apply an invitation or update from an e-mail to your calendar — without the Thunderbird glitches.

    Example: `nextcloud-calendar event import ~/Downloads/invite.eml --accept`
    Updates for one occurrence are merged into the stored series in its own time
    form, so the original and the moved occurrence never both show (and neither vanishes).
    """
    from ..itip import (
        apply_cancel,
        by_uid,
        merge_request,
        method_of,
        new_object,
        read_calendar_file,
    )

    if sum((accept, decline, tentative)) > 1:
        raise ValidationError("pass at most one of --accept, --decline, --tentative.")
    partstat = "ACCEPTED" if accept else "DECLINED" if decline else "TENTATIVE" if tentative else None
    obj = ctx_obj(ctx)
    local, me, dav = obj.local, obj.me(), obj.dav()
    incoming = read_calendar_file(file)
    method = method_of(incoming)
    groups = by_uid(incoming)
    if not groups:
        raise ValidationError(f"{file} contains no events.")
    results = []
    for uid, comps in groups.items():
        existing = dav.objects_by_uid(uid)
        if len(existing) > 1:
            raise ValidationError(
                f"the event {uid} is stored {len(existing)} times ({', '.join(o.id for o in existing)}). "
                "Run `nextcloud-calendar diagnose` and delete the duplicate first."
            )
        cur = existing[0] if existing else None
        if method == "CANCEL":
            if cur is None:
                results.append({"uid": uid, "action": "none", "notes": ["not in your calendar; nothing to cancel."]})
                continue
            edited, notes = apply_cancel(cur, comps, local)
            rep = obj.writer().save(cur, edited, notify=False, action="import-cancel")
        else:
            if cur is None:
                cal = dav.calendar(calendar or obj.profile().default_calendar)
                edited = new_object(cal.slug, cal.href, cal.name, incoming, uid, comps)
                notes = ["added to " + cal.slug + "."]
            else:
                edited, notes = merge_request(cur, incoming, comps, me, local, force=force)
            if partstat:
                for c in edited.events():
                    set_partstat(c, me, partstat)
            rep = obj.writer().save(cur, edited, notify=notify, action="import", attendee_notify_ok=True)
        out = rep.to_dict()
        out["method"] = method
        out["notes"] = notes + out["notes"]
        if rep.obj is not None:
            now = dt.datetime.now(local)
            nxt = rep.obj.occurrences(now - dt.timedelta(days=1), now + dt.timedelta(days=400), local)
            changed = [c.get("RECURRENCE-ID") for c in comps if c.get("RECURRENCE-ID") is not None]
            out["event"] = _affected(rep.obj, changed[0].dt if changed else None, local, me) if changed else (
                serialize.occurrence(nxt[0], me, local) if nxt else None)
        results.append(out)
    obj.emitter.emit(results if len(results) > 1 else results[0])

