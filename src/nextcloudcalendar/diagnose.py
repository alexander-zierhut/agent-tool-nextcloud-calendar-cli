"""Find (and repair) series that clients show differently — the answer no API gives.

Every finding here is a state in which two calendar clients, or a client and the
server, disagree about which occurrences exist. The 05.11.26 incident had two at
once (observed, reproduced in spike/s2_quiet.out):

  occurrence-form-mismatch  the series is floating, the moved occurrence carries a
                            TZID -> Thunderbird shows the original AND the moved one.
  excluded-but-changed      an EXDATE names an occurrence that also has an override
                            -> Thunderbird shows neither, Nextcloud shows the moved one.
  orphan-occurrence         an override whose RECURRENCE-ID is not an occurrence of
                            the rule -> clients either drop it or show it extra.
  duplicate-uid             the same UID stored twice -> the meeting shows twice.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .ical import EventObject, form_of, instant_key, remove_exdate, write_dt
from .timeparse import fmt

_SEVERITY = {
    "occurrence-form-mismatch": "error",
    "excluded-but-changed": "error",
    "orphan-occurrence": "warning",
    "duplicate-uid": "warning",
}
FIXABLE = frozenset({"occurrence-form-mismatch", "excluded-but-changed"})


def _summary(obj: EventObject) -> str | None:
    m = obj.master() or (obj.events()[0] if obj.events() else None)
    return str(m.get("SUMMARY")) if m is not None and m.get("SUMMARY") else None


def _finding(obj: EventObject, code: str, message: str, occurrence=None) -> dict:
    return {
        "id": obj.id,
        "summary": _summary(obj),
        "code": code,
        "severity": _SEVERITY[code],
        "occurrence": fmt(occurrence.dt if hasattr(occurrence, "dt") else occurrence) if occurrence is not None else None,
        "fixable": code in FIXABLE,
        "message": message,
    }


def _forms_clash(master_form, rid_form) -> bool:
    """Floating vs zoned, or date vs date-time. (UTC vs a TZID is fine: both name an instant.)"""
    def cls(f):
        return "date" if f.kind == "date" else ("floating" if f.kind == "floating" else "zoned")
    return cls(master_form) != cls(rid_form)


def check_object(obj: EventObject, local: dt.tzinfo) -> list[dict]:
    out: list[dict] = []
    master = obj.master()
    if master is None or master.get("DTSTART") is None:
        return out
    mform = form_of(master.get("DTSTART"))
    ex_keys = {instant_key(v.dt, local) for v in obj.exdate_values()}
    has_rule = master.get("RRULE") is not None or master.get("RDATE") is not None
    for ov in obj.overrides():
        rid = ov.get("RECURRENCE-ID")
        rform = form_of(rid)
        key = instant_key(rid, local)
        if _forms_clash(mform, rform):
            out.append(_finding(
                obj, "occurrence-form-mismatch",
                f"the series starts are {mform.describe()} but this changed occurrence is identified as "
                f"{rform.describe()}. Clients that compare the text (Thunderbird) show the original occurrence "
                "in addition to the changed one.",
                rid,
            ))
        if key in ex_keys:
            out.append(_finding(
                obj, "excluded-but-changed",
                "this occurrence is both excluded (EXDATE) and changed (override). Thunderbird hides both, "
                "Nextcloud's web calendar shows the changed one.",
                rid,
            ))
        if has_rule:
            around = rid.dt
            if key not in obj.series_instances(around, local):
                out.append(_finding(
                    obj, "orphan-occurrence",
                    "this changed occurrence does not match any occurrence of the series rule (the series was "
                    "probably moved after it was changed). Clients may drop it or show it extra.",
                    rid,
                ))
    return out


def check_duplicates(objs: list[EventObject]) -> list[dict]:
    by_uid: dict[str, list[EventObject]] = defaultdict(list)
    for o in objs:
        if o.uid:
            by_uid[o.uid].append(o)
    out = []
    for uid, group in by_uid.items():
        hrefs = {o.href for o in group}
        if len(hrefs) > 1:
            first = group[0]
            f = _finding(
                first, "duplicate-uid",
                "the same event is stored " + str(len(hrefs)) + " times: " + ", ".join(sorted(o.id for o in group))
                + ". It shows up more than once; delete the copy you do not want.",
            )
            f["duplicates"] = sorted(o.id for o in group)
            out.append(f)
    return out


def repair(obj: EventObject, local: dt.tzinfo) -> list[dict]:
    """Apply every fixable finding to *obj* in place; returns what was done."""
    done: list[dict] = []
    master = obj.master()
    if master is None:
        return done
    mform = form_of(master.get("DTSTART"))
    for ov in obj.overrides():
        rid = ov.get("RECURRENCE-ID")
        if _forms_clash(mform, form_of(rid)):
            done.append({"code": "occurrence-form-mismatch", "occurrence": fmt(rid.dt),
                         "action": f"rewrote the occurrence in the series' form ({mform.describe()})"})
            align_override(obj, ov, local)
    for ov in obj.overrides():
        if remove_exdate(obj, ov.get("RECURRENCE-ID"), local):
            done.append({"code": "excluded-but-changed", "occurrence": fmt(ov.get("RECURRENCE-ID").dt),
                         "action": "removed the EXDATE so the changed occurrence shows everywhere"})
    return done


def align_override(obj: EventObject, ov, local: dt.tzinfo) -> None:
    """Rewrite an override's RECURRENCE-ID (and its DTSTART/DTEND, if they share
    the clash) in the master's form, keeping every instant unchanged."""
    master = obj.master()
    mform = form_of(master.get("DTSTART"))
    for name in ("RECURRENCE-ID", "DTSTART", "DTEND"):
        prop = ov.get(name)
        if prop is None:
            continue
        if name != "RECURRENCE-ID" and not _forms_clash(mform, form_of(prop)):
            continue
        write_dt(ov, name, prop.dt, mform, local)
