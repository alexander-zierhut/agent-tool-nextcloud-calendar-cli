"""Writing an event without mailing people by accident — and proving it.

Nextcloud does server-side scheduling (RFC 6638): a PUT or DELETE of an event that
has an ORGANIZER and ATTENDEEs can make the *server* e-mail other people. Which
writes do that was measured against Nextcloud 35.0.2 with a mail catcher
(spike/s*_*.out); the rules this module relies on:

  attendee side (someone else organises)
    * ORGANIZER;SCHEDULE-AGENT=CLIENT turns server scheduling off for the event:
      nothing is ever sent, whatever changes. Thunderbird stores invites it
      received by e-mail exactly like this.
    * Without it, creating/declining/deleting/adding an override CAN send a REPLY,
      depending on details of the stored object (whether it carries LAST-MODIFIED,
      RRULE). Too subtle to predict, so quiet writes always set CLIENT.
    * A time change made by an attendee is never sent (no iTIP way to say it).
  organizer side (I organise, others attend)
    * The server mails attendees only if a VEVENT's SEQUENCE / LAST-MODIFIED /
      RRULE / RECURRENCE-ID changed, or a component is new
      (OCA\\DAV\\CalDAV\\EventComparisonService). Keeping SEQUENCE and LAST-MODIFIED
      untouched keeps a move/resize/cancel quiet.
    * Internal attendees (users on the same server) get their copy updated even
      then — that is calendar delivery, not mail.
    * A new override (one changed occurrence) ALWAYS mails everyone. Setting
      SCHEDULE-AGENT=CLIENT on the attendees to prevent that makes the server
      cancel the event in internal attendees' calendars — so we refuse instead.
    * DELETE with `Schedule-Reply: F` sends nothing (internal copies stay);
      a plain DELETE mails CANCEL to every attendee.
  both
    * Events whose last occurrence is in the past never mail.
    * After delivery the server writes SCHEDULE-STATUS onto ORGANIZER/ATTENDEE
      (1.1 = mailed, 1.0 = not sent, 1.2/2.0 = delivered internally). Every write
      here strips it first and re-reads it after: the result reports what the
      server DID, not what we expected.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field

from .dav import Dav
from .errors import SchedulingRefused
from .ical import (
    EventObject,
    Role,
    instant_key,
    role_of,
    schedule_agent_client,
    schedule_status,
    set_schedule_agent,
    strip_schedule_status,
    touch,
)


@dataclass
class WriteReport:
    action: str
    mode: str
    role: str
    obj: EventObject | None = None
    deleted: bool = False
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scheduling: list[dict] = field(default_factory=list)
    steps: int = 0

    def to_dict(self) -> dict:
        mailed = sorted({s["recipient"] for s in self.scheduling if s["status"] == "1.1"})
        internal = sorted({s["recipient"] for s in self.scheduling if s["status"] in ("1.2", "2.0")})
        out = {
            "action": self.action,
            "mode": self.mode,
            "role": self.role,
            "mailed": mailed,
            "deliveredInternally": internal,
            "scheduling": self.scheduling,
            "notes": self.notes,
            "warnings": self.warnings,
        }
        if self.obj is not None:
            out["id"] = self.obj.id
            out["uid"] = self.obj.uid
        if self.deleted:
            out["deleted"] = True
        return out


def _rid_keys(obj: EventObject | None, local: dt.tzinfo) -> dict[str, object]:
    if obj is None:
        return {}
    out = {}
    for c in obj.events():
        rid = c.get("RECURRENCE-ID")
        out["master" if rid is None else instant_key(rid, local)] = c
    return out


def _restore_change_markers(original: EventObject, edited: EventObject, local: dt.tzinfo) -> None:
    """Give every component of *edited* the SEQUENCE and LAST-MODIFIED it had in
    *original* (including their absence) — the organizer-side quiet rule."""
    before = _rid_keys(original, local)
    for key, comp in _rid_keys(edited, local).items():
        old = before.get(key)
        if old is None:
            continue
        for name in ("SEQUENCE", "LAST-MODIFIED"):
            while comp.get(name) is not None:
                comp.pop(name)
            if old.get(name) is not None:
                comp.add(name, old.get(name), encode=False)


def _bump_changed(original: EventObject | None, edited: EventObject, local: dt.tzinfo) -> None:
    """Organizer --notify: every component that differs gets SEQUENCE+1 and a fresh LAST-MODIFIED."""
    before = _rid_keys(original, local)
    floor = max((int(c.get("SEQUENCE", 0) or 0) for c in (original.events() if original else [])), default=0)
    for key, comp in _rid_keys(edited, local).items():
        old = before.get(key)
        if old is not None and _same(old, comp):
            continue
        seq = max(int(comp.get("SEQUENCE", 0) or 0), floor) + 1
        while comp.get("SEQUENCE") is not None:
            comp.pop("SEQUENCE")
        comp.add("SEQUENCE", seq)
        touch(comp, last_modified=True)


def _same(a, b) -> bool:
    ignore = {"DTSTAMP", "LAST-MODIFIED", "SEQUENCE"}

    def norm(c):
        return sorted((k, c[k].to_ical() if hasattr(c[k], "to_ical") else str(c[k])) for k in c.keys() if k not in ignore and k != "ATTENDEE") + \
            sorted(str(x) + str(dict(x.params)) for x in (c.get("ATTENDEE") if isinstance(c.get("ATTENDEE"), list) else [c.get("ATTENDEE")] if c.get("ATTENDEE") else []))
    try:
        return norm(a) == norm(b)
    except Exception:
        return False


class Writer:
    def __init__(self, dav: Dav, me: Iterable[str], local: dt.tzinfo) -> None:
        self.dav = dav
        self.client = dav.client
        self.me = [m.lower() for m in me]
        self.local = local

    # ---- helpers -----------------------------------------------------
    def role(self, obj: EventObject) -> Role:
        comps = obj.events()
        base = obj.master() or (comps[0] if comps else None)
        if base is None:
            return Role("personal")
        return role_of(base, self.me)

    def _put(self, obj: EventObject, *, create: bool = False) -> EventObject:
        strip_schedule_status(obj)
        self.client.put(obj.href, obj.to_ical(), etag=None if create else obj.etag, create=create)
        return self.dav.reload(obj)

    def _verify_quiet(self, rep: WriteReport) -> None:
        mailed = [s["recipient"] for s in rep.scheduling if s["status"] == "1.1"]
        if mailed:
            rep.warnings.append(
                "the server e-mailed " + ", ".join(sorted(set(mailed))) + " although a quiet write was requested. "
                "Please report this (`nextcloud-calendar report`) — the quiet rules may not hold for this server version."
            )

    # ---- save (create or update) --------------------------------------
    def save(self, original: EventObject | None, edited: EventObject, *, notify: bool, action: str,
             attendee_notify_ok: bool = False) -> WriteReport:
        """Write *edited* (a modified copy of *original*, or a new object when
        *original* is None) following the scheduling rules above."""
        role = self.role(original or edited)
        rep = WriteReport(action=action, mode="notify" if notify else "quiet", role=role.kind)
        create = original is None

        if role.kind == "personal":
            for c in edited.events():
                touch(c, last_modified=True)
            if notify:
                rep.notes.append("nobody else is on this event; there is no one to notify.")
            obj = self._put(edited, create=create)
            rep.obj, rep.steps = obj, 1
            rep.scheduling = schedule_status(obj)
            return rep

        if role.kind == "attendee":
            return self._save_attendee(original, edited, rep, notify=notify, allowed=attendee_notify_ok)
        return self._save_organizer(original, edited, rep, notify=notify)

    def _save_attendee(self, original, edited, rep: WriteReport, *, notify: bool, allowed: bool) -> WriteReport:
        was_client = original is not None and all(schedule_agent_client(c, "organizer") for c in original.events())
        for c in edited.events():
            touch(c, last_modified=True)
        if not notify:
            set_schedule_agent(edited, "organizer", client=True)
            obj = self._put(edited, create=original is None)
            rep.obj, rep.steps = obj, 1
            rep.scheduling = schedule_status(obj)
            if not was_client:
                rep.notes.append(
                    "server-side replies are now off for this event (ORGANIZER;SCHEDULE-AGENT=CLIENT), "
                    "the same way Thunderbird stores invites it got by e-mail. Use --notify on "
                    "`event respond` when the organizer should hear from you."
                )
            self._verify_quiet(rep)
            return rep

        if not allowed:
            raise SchedulingRefused(
                f"you are an attendee of this event (organizer: {self.role(original or edited).organizer}); "
                "the server has no way to tell the organizer about this kind of change, so --notify cannot be honoured. "
                "Leave out --notify to change only your own calendar, or ask the organizer to change the meeting.",
                detail={"role": "attendee"},
            )
        if original is not None and any(c.get("LAST-MODIFIED") is None for c in original.events()):
            # Step 1 (silent): make sure the stored copy carries LAST-MODIFIED, with
            # scheduling off — a REPLY is only mailed when the stored copy has it.
            prep = original.copy()
            set_schedule_agent(prep, "organizer", client=True)
            for c in prep.events():
                if c.get("LAST-MODIFIED") is None:
                    c.add("LAST-MODIFIED", dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(seconds=2))
            stored = self._put(prep)
            edited.etag = stored.etag
            rep.steps += 1
        set_schedule_agent(edited, "organizer", client=False)
        obj = self._put(edited, create=original is None)
        rep.steps += 1
        rep.scheduling = schedule_status(obj)
        if was_client:
            # Step 3 (silent): hand scheduling back to the mail client, as before.
            restore = obj.copy()
            set_schedule_agent(restore, "organizer", client=True)
            obj = self._put(restore)
            rep.steps += 1
        rep.obj = obj
        if not any(s["status"] == "1.1" for s in rep.scheduling):
            got = ", ".join(f"{s['recipient']}: {s['status']} ({s['meaning']})" for s in rep.scheduling) or "no delivery recorded"
            rep.warnings.append(
                f"--notify was requested but the server did not e-mail the organizer ({got}). "
                "Typical causes: the event is in the past, or nothing reply-worthy changed (only a new answer is sent)."
            )
        return rep

    def _save_organizer(self, original, edited, rep: WriteReport, *, notify: bool) -> WriteReport:
        local = self.local
        create = original is None
        if notify:
            if not create:
                _bump_changed(original, edited, local)
            else:
                set_schedule_agent(edited, "attendees", client=False)
            obj = self._put(edited, create=create)
            rep.obj, rep.steps = obj, 1
            rep.scheduling = schedule_status(obj)
            if not any(s["status"] == "1.1" for s in rep.scheduling) and not any(s["status"] in ("1.2", "2.0") for s in rep.scheduling):
                rep.warnings.append("--notify was requested but the server recorded no delivery (the event may be in the past).")
            return rep

        if create:
            set_schedule_agent(edited, "attendees", client=True)
            rep.notes.append(
                "attendees are recorded but NOT invited (ATTENDEE;SCHEDULE-AGENT=CLIENT). "
                "Re-run with --notify to send invitations."
            )
            obj = self._put(edited, create=True)
            rep.obj, rep.steps = obj, 1
            rep.scheduling = schedule_status(obj)
            self._verify_quiet(rep)
            return rep

        added = set(_rid_keys(edited, local)) - set(_rid_keys(original, local))
        if added:
            raise SchedulingRefused(
                "you organise this meeting and the change creates a changed single occurrence; Nextcloud always e-mails "
                "every attendee about that (observed on Nextcloud 35). Re-run with --notify to send the update, or with "
                "--series to change the whole series quietly, or remove just this occurrence with `event delete --occurrence`.",
                detail={"role": "organizer", "newOccurrences": sorted(added)},
            )
        _restore_change_markers(original, edited, local)
        obj = self._put(edited)
        rep.obj, rep.steps = obj, 1
        rep.scheduling = schedule_status(obj)
        internal = [s["recipient"] for s in rep.scheduling if s["status"] in ("1.2", "2.0")]
        if internal or any(s["status"] == "1.0" for s in rep.scheduling):
            rep.notes.append(
                "no e-mail was sent. Attendees with an account on this Nextcloud see the change in their calendar "
                "(the server updates their copy silently)."
            )
        self._verify_quiet(rep)
        return rep

    # ---- delete ------------------------------------------------------
    def _delete(self, obj: EventObject, rep: WriteReport, *, schedule_reply: bool) -> None:
        note = self.dav.delete_object(obj, schedule_reply=schedule_reply)
        rep.steps += 1
        if note:
            rep.notes.append(note)

    def delete(self, obj: EventObject, *, notify: bool) -> WriteReport:
        role = self.role(obj)
        rep = WriteReport(action="delete", mode="notify" if notify else "quiet", role=role.kind, obj=obj, deleted=True)
        if role.kind == "personal":
            self._delete(obj, rep, schedule_reply=True)
            return rep
        if role.kind == "attendee":
            current = obj
            if notify:
                if role.my_status == "DECLINED":
                    rep.notes.append("you had already declined; no new reply is sent.")
                else:
                    from .ical import set_partstat

                    edited = obj.copy()
                    for c in edited.events():
                        set_partstat(c, self.me, "DECLINED")
                    sub = self._save_attendee(obj, edited, WriteReport("decline", "notify", "attendee"), notify=True, allowed=True)
                    rep.scheduling, rep.warnings, rep.steps = sub.scheduling, sub.warnings, sub.steps
                    current = sub.obj
            if not all(schedule_agent_client(c, "organizer") for c in current.events()):
                prep = current.copy()
                set_schedule_agent(prep, "organizer", client=True)
                current = self._put(prep)
                rep.steps += 1
            self._delete(current, rep, schedule_reply=False)
            if not notify:
                rep.notes.append("removed from your calendar only; the organizer was not told. Use --notify to decline instead.")
            return rep
        # organizer
        if notify:
            self._delete(obj, rep, schedule_reply=True)
            rep.notes.append(
                "the server sends a cancellation to every attendee on DELETE (observed). After deletion there is no "
                "object left to read SCHEDULE-STATUS from, so delivery cannot be confirmed here."
            )
            rep.scheduling = [{"recipient": a, "as": "attendee", "status": "expected", "meaning": "CANCEL sent by the server"} for a in role.others]
            return rep
        self._delete(obj, rep, schedule_reply=False)
        rep.notes.append(
            "deleted without telling anyone (Schedule-Reply: F). Attendees still have the meeting in their calendars; "
            "use --notify to cancel it for them."
        )
        return rep
