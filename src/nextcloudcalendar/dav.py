"""Server-level operations: discovery, calendars, queries, trash.

Turns DAV responses into plain dicts and `EventObject`s. Knows Nextcloud's URL
layout only through discovery (current-user-principal -> calendar-home-set), so a
Nextcloud under a sub-path or with a differing login name still works.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from xml.sax.saxutils import escape

from .client import NS, Client, q
from .errors import NotFoundError, ValidationError
from .ical import UTC, EventObject

_CAL_PROPS = (
    "<d:displayname/><d:resourcetype/><c:supported-calendar-component-set/><cs:getctag/>"
    "<ical:calendar-color/><oc:owner-principal/><d:current-user-privilege-set/><c:calendar-description/>"
)


def _ical_utc(value: dt.datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass
class Calendar:
    slug: str
    name: str
    href: str
    color: str | None
    components: list[str]
    writable: bool
    owner: str | None
    ctag: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.slug,
            "name": self.name,
            "color": self.color,
            "components": self.components,
            "writable": self.writable,
            "owner": self.owner,
            "href": self.href,
        }


class Dav:
    def __init__(self, client: Client) -> None:
        self.client = client
        self._principal: dict | None = None
        self._calendars: list[Calendar] | None = None

    # ---- discovery ---------------------------------------------------
    def principal(self) -> dict:
        if self._principal is None:
            root = self.client.propfind(self.client.dav_root + "/", "<d:current-user-principal/>")
            href = root[0].hrefs("d:current-user-principal")[0] if root and root[0].hrefs("d:current-user-principal") else None
            if not href:
                raise ValidationError("the server did not report a current-user-principal — is this a Nextcloud/CalDAV URL?")
            info = self.client.propfind(
                href,
                "<c:calendar-home-set/><c:schedule-inbox-URL/><c:calendar-user-address-set/>"
                "<d:displayname/><c:schedule-default-calendar-URL/>",
            )[0]
            homes = info.hrefs("c:calendar-home-set")
            if not homes:
                raise ValidationError("the principal has no calendar-home-set (is the calendar app/DAV disabled?)")
            addresses = [h[7:].lower() for h in info.hrefs("c:calendar-user-address-set") if h.lower().startswith("mailto:")]
            default = info.hrefs("c:schedule-default-calendar-URL")
            self._principal = {
                "href": href,
                "home": homes[0],
                "displayName": info.text("d:displayname"),
                "addresses": addresses,
                "defaultCalendar": default[0].rstrip("/").rsplit("/", 1)[-1] if default else None,
            }
        return self._principal

    def calendars(self, *, include_readonly: bool = True) -> list[Calendar]:
        if self._calendars is None:
            home = self.principal()["home"]
            out: list[Calendar] = []
            for r in self.client.propfind(home, _CAL_PROPS, depth="1"):
                if not r.has("d:resourcetype", "c:calendar"):
                    continue
                comps_el = r.props.get(q("c:supported-calendar-component-set"))
                comps = [c.get("name") for c in comps_el.findall("c:comp", NS)] if comps_el is not None else []
                priv = r.props.get(q("d:current-user-privilege-set"))
                writable = True
                if priv is not None:
                    names = {p[0].tag for p in priv.findall("d:privilege", NS) if len(p)}
                    writable = bool(names & {q("d:write"), q("d:write-content"), q("d:all")})
                slug = r.href.rstrip("/").rsplit("/", 1)[-1]
                out.append(Calendar(
                    slug=slug,
                    name=r.text("d:displayname") or slug,
                    href=r.href if r.href.endswith("/") else r.href + "/",
                    color=r.text("ical:calendar-color"),
                    components=[c for c in comps if c],
                    writable=writable,
                    owner=(r.text("oc:owner-principal") or "").rsplit("/", 1)[-1] or None,
                    ctag=r.text("cs:getctag"),
                ))
            self._calendars = out
        cals = [c for c in self._calendars if "VEVENT" in c.components or not c.components]
        return cals if include_readonly else [c for c in cals if c.writable]

    def calendar(self, ref: str | None) -> Calendar:
        """Resolve a calendar by slug, display name (case-insensitive), or unique substring."""
        cals = self.calendars()
        if not ref:
            default = self.principal().get("defaultCalendar")
            for c in cals:
                if c.slug == default:
                    return c
            writable = [c for c in cals if c.writable]
            if writable:
                return writable[0]
            raise NotFoundError("no writable calendar found.")
        low = ref.lower()
        for c in cals:
            if c.slug == ref or c.name.lower() == low:
                return c
        hits = [c for c in cals if low in c.slug.lower() or low in c.name.lower()]
        if len(hits) == 1:
            return hits[0]
        names = ", ".join(sorted(f"{c.slug} ({c.name})" for c in cals))
        if hits:
            raise ValidationError(f"calendar '{ref}' is ambiguous. Matches: " + ", ".join(f"{c.slug} ({c.name})" for c in hits))
        raise NotFoundError(f"no calendar matching '{ref}'. Available: {names}")

    # ---- objects -----------------------------------------------------
    def _query(self, cal: Calendar, filter_xml: str) -> list[EventObject]:
        body = (
            f'<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f"<d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name=\"VCALENDAR\">"
            f"<c:comp-filter name=\"VEVENT\">{filter_xml}</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
        )
        out = []
        for r in self.client.report(cal.href, body):
            data = r.text("c:calendar-data")
            if not data:
                continue
            try:
                out.append(EventObject.parse(cal.slug, r.href, r.text("d:getetag"), data, cal.name))
            except Exception:
                continue  # an unparseable object must not hide the others
        return out

    def objects_between(self, cal: Calendar, start: dt.datetime, end: dt.datetime) -> list[EventObject]:
        return self._query(cal, f'<c:time-range start="{_ical_utc(start)}" end="{_ical_utc(end)}"/>')

    def all_objects(self, cal: Calendar) -> list[EventObject]:
        return self._query(cal, "")

    def objects_by_uid(self, uid: str, cals: list[Calendar] | None = None) -> list[EventObject]:
        filt = (f'<c:prop-filter name="UID"><c:text-match collation="i;octet">{escape(uid)}</c:text-match></c:prop-filter>')
        out = []
        for cal in cals or self.calendars():
            out.extend(o for o in self._query(cal, filt) if o.uid == uid)
        return out

    def get(self, cal: Calendar, name: str) -> EventObject:
        href = cal.href + name
        text, etag = self.client.get(href)
        return EventObject.parse(cal.slug, href, etag, text, cal.name)

    def reload(self, obj: EventObject) -> EventObject:
        text, etag = self.client.get(obj.href)
        return EventObject.parse(obj.calendar, obj.href, etag, text, obj.calendar_name)

    # ---- trash (Nextcloud >= 22) -------------------------------------
    def trash(self) -> list[dict]:
        home = self.principal()["home"]
        body = (
            '<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
            'xmlns:nc="http://nextcloud.com/ns"><d:prop><d:getetag/><nc:deleted-at/><nc:calendar-uri/><c:calendar-data/></d:prop>'
            '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"/></c:comp-filter></c:filter></c:calendar-query>'
        )
        out = []
        for r in self.client.report(home + "trashbin/objects/", body):
            data = r.text("c:calendar-data") or ""
            obj = None
            try:
                obj = EventObject.parse(r.text("nc:calendar-uri") or "?", r.href, None, data)
            except Exception:
                pass
            master = (obj.master() or (obj.events()[0] if obj and obj.events() else None)) if obj else None
            start = master.get("DTSTART").dt if master is not None and master.get("DTSTART") is not None else None
            out.append({
                "id": r.href.rstrip("/").rsplit("/", 1)[-1],
                "calendar": r.text("nc:calendar-uri"),
                "deletedAt": r.text("nc:deleted-at"),
                "uid": obj.uid if obj else None,
                "summary": str(master.get("SUMMARY")) if master is not None and master.get("SUMMARY") else None,
                "start": start.isoformat() if start is not None else None,
                "recurring": obj.is_recurring() if obj else None,
                "href": r.href,
            })
        out.sort(key=lambda t: t["deletedAt"] or "", reverse=True)
        return out

    def _trash_item(self, trash_id: str) -> dict:
        items = {t["id"]: t for t in self.trash()}
        item = items.get(trash_id) or items.get(trash_id + ".ics")
        if item is None:
            avail = ", ".join(f"{t['id']} ({t['summary']})" for t in list(items.values())[:25])
            raise NotFoundError(f"nothing in the trash with id '{trash_id}'. In the trash: {avail or 'nothing'}")
        return item

    def purge(self, trash_id: str) -> dict:
        """Delete a trash entry for good."""
        item = self._trash_item(trash_id)
        self.client.delete(item["href"])
        return item

    def delete_object(self, obj: EventObject, *, schedule_reply: bool, etag: str | None = None) -> str | None:
        """DELETE that survives Nextcloud's trash-name clash.

        Observed: deleting X.ics while an older deleted X.ics still sits in the
        trash (as X-deleted.ics) fails with 403 "can't be moved into the trashbin".
        The older copy of the SAME event (same calendar, same UID) is superseded by
        this deletion, so it is purged and the delete retried. Returns a note when
        that happened."""
        from .errors import AuthError

        try:
            self.client.delete(obj.href, etag=etag if etag is not None else obj.etag, schedule_reply=schedule_reply)
            return None
        except AuthError as exc:
            if "trashbin" not in exc.message:
                raise
            olds = [t for t in self.trash() if t["calendar"] == obj.calendar and t["uid"] == obj.uid]
            if len(olds) != 1:
                raise AuthError(
                    f"Nextcloud refuses to delete {obj.id}: an older deleted copy with the same file name is in the "
                    "trash. Remove it with `nextcloud-calendar trash purge ID` (see `trash list`) and retry.",
                    detail=exc.detail,
                ) from exc
            self.client.delete(olds[0]["href"])
            self.client.delete(obj.href, etag=etag if etag is not None else obj.etag, schedule_reply=schedule_reply)
            return (f"an older deleted copy of this event (trash id {olds[0]['id']}, deleted {olds[0]['deletedAt']}) "
                    "was removed from the trash to make room; the copy deleted now is restorable.")

    def restore(self, trash_id: str) -> dict:
        item = self._trash_item(trash_id)
        home = self.principal()["home"]
        self.client.move(item["href"], home + "trashbin/restore/" + item["id"])
        return item
