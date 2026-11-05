"""What a human (or an agent relaying one) types for times, and what it means.

The wire's representation of time is never what a human types: iCalendar wants
``20261106T113000`` in a named zone, people say ``11:30`` or ``tomorrow``.
Everything is read in the profile's zone unless an offset is given.
"""

from __future__ import annotations

import datetime as dt
import re

from .errors import ValidationError

_WEEKDAYS = {
    "mon": 0, "monday": 0, "mo": 0, "montag": 0,
    "tue": 1, "tuesday": 1, "di": 1, "dienstag": 1,
    "wed": 2, "wednesday": 2, "mi": 2, "mittwoch": 2,
    "thu": 3, "thursday": 3, "do": 3, "donnerstag": 3,
    "fri": 4, "friday": 4, "fr": 4, "freitag": 4,
    "sat": 5, "saturday": 5, "sa": 5, "samstag": 5,
    "sun": 6, "sunday": 6, "so": 6, "sonntag": 6,
}
_DUR = re.compile(r"^(?P<sign>[+-])?\s*(?:(?P<d>\d+(?:\.\d+)?)d)?\s*(?:(?P<h>\d+(?:\.\d+)?)h)?\s*(?:(?P<m>\d+)m(?:in)?)?$")
_TIME = re.compile(r"^(?P<h>\d{1,2})(?::(?P<m>\d{2}))?$")


def today(local: dt.tzinfo) -> dt.date:
    return dt.datetime.now(local).date()


def parse_date(text: str, local: dt.tzinfo) -> dt.date:
    t = text.strip().lower()
    base = today(local)
    if t in ("today", "heute"):
        return base
    if t in ("tomorrow", "morgen"):
        return base + dt.timedelta(days=1)
    if t in ("yesterday", "gestern"):
        return base - dt.timedelta(days=1)
    m = re.fullmatch(r"([+-]\d+)d", t)
    if m:
        return base + dt.timedelta(days=int(m.group(1)))
    if t in _WEEKDAYS:
        ahead = (_WEEKDAYS[t] - base.weekday()) % 7 or 7
        return base + dt.timedelta(days=ahead)
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})?", t)
    if m:
        year = int(m.group(3)) if m.group(3) else base.year
        year = year + 2000 if year < 100 else year
        return dt.date(year, int(m.group(2)), int(m.group(1)))
    try:
        return dt.date.fromisoformat(t)
    except ValueError as exc:
        raise ValidationError(
            f"cannot read the date '{text}'. Use YYYY-MM-DD, DD.MM.YYYY, today, tomorrow, a weekday, or +3d."
        ) from exc


def parse_datetime(text: str, local: dt.tzinfo, *, on: dt.date | None = None) -> dt.datetime:
    """'2026-11-06T11:30', '2026-11-06 11:30', '11:30' (on *on* / today),
    'tomorrow 9:00', 'fri 14:00', '2026-11-06T10:30:00Z' -> aware datetime."""
    t = text.strip()
    m = _TIME.fullmatch(t)
    if m:
        d = on or today(local)
        return dt.datetime(d.year, d.month, d.day, int(m.group("h")), int(m.group("m") or 0), tzinfo=local)
    parts = t.replace("T", " ", 1).split() if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", t) else t.split()
    if len(parts) == 2 and _TIME.fullmatch(parts[1]):
        d = parse_date(parts[0], local)
        tm = _TIME.fullmatch(parts[1])
        return dt.datetime(d.year, d.month, d.day, int(tm.group("h")), int(tm.group("m") or 0), tzinfo=local)
    try:
        v = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        v = None
    if v is not None:
        return v if v.tzinfo else v.replace(tzinfo=local)
    raise ValidationError(
        f"cannot read the time '{text}'. Use 'YYYY-MM-DD HH:MM', 'HH:MM', 'tomorrow 9:00' or 'fri 14:00'."
    )


def parse_when(text: str, local: dt.tzinfo, *, on: dt.date | None = None) -> dt.date | dt.datetime:
    """A date (all-day) or a date-time, whichever the text is."""
    t = text.strip()
    if _TIME.fullmatch(t) or " " in t or "T" in t[4:] or ":" in t:
        return parse_datetime(t, local, on=on)
    return parse_date(t, local)


def parse_duration(text: str) -> dt.timedelta:
    """'90m', '1h30m', '2.5h', '1d', '+30m', '-1h', 'PT1H30M' -> timedelta (signed)."""
    t = text.strip().lower().replace(" ", "")
    if t.startswith(("pt", "+pt", "-pt", "p")):
        sign = -1 if t.startswith("-") else 1
        m = re.fullmatch(r"[+-]?p(?:(\d+)d)?(?:t(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?)?", t)
        if m and any(m.groups()):
            d, h, mi, s = (int(x or 0) for x in m.groups())
            return sign * dt.timedelta(days=d, hours=h, minutes=mi, seconds=s)
    m = _DUR.fullmatch(t)
    if not m or not any(m.group(k) for k in ("d", "h", "m")):
        raise ValidationError(f"cannot read the duration '{text}'. Use e.g. 30m, 1h30m, 2.5h, 1d, +15m, -1h.")
    sign = -1 if m.group("sign") == "-" else 1
    return sign * dt.timedelta(
        days=float(m.group("d") or 0), hours=float(m.group("h") or 0), minutes=int(m.group("m") or 0)
    )


def fmt(value: dt.date | dt.datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="minutes")
    return value.isoformat()
