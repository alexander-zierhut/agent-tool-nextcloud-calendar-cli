"""`diagnose` — find series that clients show differently, and repair them quietly."""

from __future__ import annotations

import datetime as dt

import typer

from ..diagnose import FIXABLE, check_duplicates, check_object, repair
from ..resolve import resolve_one
from ._shared import CALENDAR_OPT_HELP, ctx_obj

_COLUMNS = [("Severity", "severity"), ("Code", "code"), ("Summary", "summary"), ("Occurrence", "occurrence"), ("ID", "id")]


def diagnose(
    ctx: typer.Context,
    event: str = typer.Option(None, "--event", help="Check just this event (id, UID or title)."),
    calendar: str = typer.Option(None, "--calendar", help=CALENDAR_OPT_HELP),
    all_: bool = typer.Option(False, "--all", help="Check every stored event, not just those from 30 days ago to a year ahead."),
    fix: bool = typer.Option(False, "--fix", help="Repair what is repairable, quietly (nobody is mailed)."),
    exit_code: bool = typer.Option(False, "--exit-code", help="Exit 20 when there are findings (default: findings exit 0)."),
) -> None:
    """Find duplicated or vanished occurrences before you notice them in Thunderbird.

    Example: `nextcloud-calendar diagnose`, then `nextcloud-calendar diagnose --fix`
    Checks: occurrence-form-mismatch (original + moved both shown),
    excluded-but-changed (moved occurrence vanished), orphan-occurrence,
    duplicate-uid. Findings are observations: exit 0 unless --exit-code.
    """
    obj = ctx_obj(ctx)
    local = obj.local
    dav = obj.dav()
    if event:
        objs = [resolve_one(dav, event, calendar=calendar, local=local)]
    else:
        cals = [dav.calendar(calendar)] if calendar else dav.calendars()
        now = dt.datetime.now(local)
        objs = []
        for cal in cals:
            objs.extend(dav.all_objects(cal) if all_ else dav.objects_between(cal, now - dt.timedelta(days=30), now + dt.timedelta(days=365)))
    findings: list[dict] = []
    for o in objs:
        findings.extend(check_object(o, local))
    findings.extend(check_duplicates(objs))
    out: dict = {"checked": len(objs), "findings": findings}
    if fix:
        fixed = []
        writer = obj.writer()
        for o in objs:
            if not any(f["id"] == o.id and f["code"] in FIXABLE for f in findings):
                continue
            edited = o.copy()
            done = repair(edited, local)
            if not done:
                continue
            rep = writer.save(o, edited, notify=False, action="repair")
            fixed.append({"id": o.id, "repairs": done, "write": rep.to_dict()})
        out["fixed"] = fixed
        remaining = []
        for o in objs:
            if any(fx["id"] == o.id for fx in fixed):
                remaining.extend(check_object(dav.reload(o), local))
            else:
                remaining.extend(f for f in findings if f["id"] == o.id and f["code"] != "duplicate-uid")
        remaining.extend(check_duplicates(objs))
        out["remaining"] = remaining
    if obj.emitter.fmt.value != "json" and not obj.emitter.fields:
        obj.emitter.emit(out.get("remaining", findings), columns=_COLUMNS, empty="(no problems found)")
    else:
        obj.emitter.emit(out)
    if exit_code and (out.get("remaining", findings)):
        raise typer.Exit(20)
