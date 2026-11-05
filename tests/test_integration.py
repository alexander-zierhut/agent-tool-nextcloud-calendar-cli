"""The CLI against a real Nextcloud 35 + Mailpit: what is stored AND who got mail.

Run: `make up && make test-integration`. Every scenario asserts the mailbox,
because "quiet" is a promise about other people's inboxes.
"""

from __future__ import annotations

import datetime as dt

import pytest
from samples import (
    BOB,
    CAROL,
    ORG,
    broken_incident,
    friday,
    invite_series,
    invite_single,
    move_mail,
    own_series,
    own_single,
    personal,
)

pytestmark = pytest.mark.integration

FRI = friday()


def _rcpts(msgs, method=None):
    return sorted({t for m in msgs if method is None or m["method"] == method for t in m["to"]})


# ---- personal events -----------------------------------------------------

def test_personal_lifecycle_and_trash_restore(world, cli):
    alex, _, mail = world
    r = cli("event", "create", "--title", "Dentist", "--start", f"{FRI} 08:30", "--duration", "45m")
    assert r.code == 0, r
    eid = r.json["id"]
    assert r.json["event"]["start"].startswith(f"{FRI}T08:30") and r.json["event"]["end"].startswith(f"{FRI}T09:15")

    r = cli("event", "move", eid, "--to", "10:00")
    assert r.code == 0, r
    assert r.json["event"]["start"].startswith(f"{FRI}T10:00") and r.json["event"]["end"].startswith(f"{FRI}T10:45")

    r = cli("event", "update", eid, "--extend", "+1h")
    assert r.code == 0 and r.json["event"]["end"].startswith(f"{FRI}T11:45"), r

    r = cli("event", "delete", eid)
    assert r.code == 0 and r.json["deleted"], r
    assert not alex.hrefs()

    t = cli("trash", "list")
    item = next(x for x in t.json if x["summary"] == "Dentist")
    r = cli("trash", "restore", item["id"])
    assert r.code == 0, r
    assert len(alex.hrefs()) == 1
    assert mail.messages() == []


def test_list_window_and_search(world, cli):
    alex, _, _ = world
    alex.put("p.ics", personal("p-1", FRI, 9))
    alex.put("s.ics", invite_series("s-1"))
    r = cli("event", "list", "--from", str(FRI), "--days", "1")
    assert r.code == 0
    assert sorted(x["summary"] for x in r.json) == ["Dentist", "Weekly"]
    r = cli("event", "list", "--from", str(FRI), "--days", "21", "--search", "weekly")
    assert len(r.json) == 3 and all(x["occurrence"] for x in r.json)


# ---- attendee side (someone else organises) --------------------------------

def test_attendee_move_one_occurrence_is_quiet_and_clean(world, cli):
    alex, _, mail = world
    alex.put("s.ics", invite_series("s-2", client=False))  # server scheduling ON: the risky case
    mail.clear()
    nxt = FRI + dt.timedelta(weeks=1)
    r = cli("event", "move", "Weekly", "--occurrence", str(nxt), "--to", "11:30")
    assert r.code == 0, r
    assert r.json["mode"] == "quiet" and r.json["role"] == "attendee" and r.json["mailed"] == []
    assert r.json["event"]["start"].startswith(f"{nxt}T11:30")
    assert mail.messages() == []
    body = alex.get("s.ics")
    assert "SCHEDULE-AGENT=CLIENT" in body  # quiet attendee writes switch server replies off
    lst = cli("event", "list", "--from", str(nxt), "--days", "1").json
    assert [x["start"][11:16] for x in lst] == ["11:30"]          # no duplicate
    assert cli("diagnose", "--event", "s-2").json["findings"] == []


def test_attendee_extend_single_quiet(world, cli):
    alex, _, mail = world
    alex.put("w.ics", invite_single("w-1", client=False))
    mail.clear()
    r = cli("event", "update", "Workshop", "--duration", "2h30m")
    assert r.code == 0, r
    assert r.json["event"]["end"].startswith(f"{FRI}T16:30") and r.json["mailed"] == []
    assert mail.messages() == []


def test_attendee_move_with_notify_is_refused(world, cli):
    alex, _, mail = world
    alex.put("w.ics", invite_single("w-2"))
    mail.clear()
    r = cli("event", "move", "Workshop", "--by", "+30m", "--notify")
    assert r.code == 8, r
    assert "organizer" in r.error["error"]
    assert mail.messages() == []


@pytest.mark.parametrize("client", [False, True], ids=["server-scheduled", "thunderbird-imported"])
def test_attendee_decline_notify_sends_exactly_one_reply(world, cli, client):
    alex, _, mail = world
    alex.put("w.ics", invite_single("w-3", client=client))
    mail.clear()
    r = cli("event", "respond", "Workshop", "declined", "--notify")
    assert r.code == 0, r
    assert r.json["mailed"] == [ORG]
    msgs = mail.messages()
    assert [(m["to"], m["method"]) for m in msgs] == [([ORG], "REPLY")]
    body = alex.get("w.ics")
    assert "PARTSTAT=DECLINED" in body
    # Thunderbird-imported invites keep client-side scheduling afterwards.
    assert ("SCHEDULE-AGENT=CLIENT" in body) == client


def test_attendee_decline_quiet_and_delete_quiet(world, cli):
    alex, _, mail = world
    alex.put("w.ics", invite_single("w-4", client=False))
    mail.clear()
    assert cli("event", "respond", "Workshop", "declined").json["mailed"] == []
    assert cli("event", "delete", "Workshop").code == 0
    assert mail.messages() == []


def test_attendee_delete_notify_declines_first(world, cli):
    alex, _, mail = world
    alex.put("w.ics", invite_single("w-5", client=False))
    mail.clear()
    r = cli("event", "delete", "Workshop", "--notify")
    assert r.code == 0, r
    assert _rcpts(mail.messages(), "REPLY") == [ORG]
    assert not alex.hrefs()


def test_attendee_delete_one_occurrence_quiet(world, cli):
    alex, _, mail = world
    alex.put("s.ics", invite_series("s-3", client=False))
    mail.clear()
    nxt = FRI + dt.timedelta(weeks=2)
    r = cli("event", "delete", "s-3", "--occurrence", str(nxt))
    assert r.code == 0, r
    assert mail.messages() == []
    assert cli("event", "list", "--from", str(nxt), "--days", "1").json == []


def test_recurring_without_occurrence_or_series_is_refused(world, cli):
    alex, _, _ = world
    alex.put("s.ics", invite_series("s-4"))
    r = cli("event", "move", "Weekly", "--by", "+30m")
    assert r.code == 7 and "--occurrence" in r.error["error"]


def test_attendee_series_move_keeps_one_per_week(world, cli):
    alex, _, mail = world
    alex.put("s.ics", invite_series("s-5"))
    mail.clear()
    r = cli("event", "move", "Weekly", "--series", "--to", "12:00")
    assert r.code == 0, r
    lst = cli("event", "list", "--from", str(FRI), "--days", "21").json
    assert [x["start"][11:16] for x in lst] == ["12:00"] * 3
    assert mail.messages() == []


# ---- organizer side ----------------------------------------------------------

def test_organizer_quiet_move_whole_event_mails_nobody_but_updates_colleague(world, cli):
    alex, bob, mail = world
    alex.put("o.ics", own_single("o-1"))
    assert _rcpts(mail.messages(), "REQUEST") == [BOB, CAROL]  # the seed itself invites (expected)
    mail.clear()
    r = cli("event", "move", "Kickoff", "--by", "+1h")
    assert r.code == 0, r
    assert r.json["mailed"] == [] and r.json["role"] == "organizer"
    assert mail.messages() == []
    assert any("T110000" in b.split("DTSTART", 1)[1][:40] for b in bob.bodies())  # bob's copy moved 10:00 -> 11:00


def test_organizer_one_occurrence_quiet_is_refused_and_notify_mails(world, cli):
    alex, _, mail = world
    alex.put("o.ics", own_series("o-2"))
    mail.clear()
    wed = FRI - dt.timedelta(days=2) + dt.timedelta(weeks=1)
    r = cli("event", "move", "Jour fixe", "--occurrence", str(wed), "--to", "12:00")
    assert r.code == 8, r
    assert mail.messages() == []
    r = cli("event", "move", "Jour fixe", "--occurrence", str(wed), "--to", "12:00", "--notify")
    assert r.code == 0, r
    assert r.json["mailed"] == [CAROL] or r.json["mailed"] == sorted([BOB, CAROL])
    assert CAROL in _rcpts(mail.messages(), "REQUEST")


def test_organizer_delete_one_occurrence_quiet(world, cli):
    alex, bob, mail = world
    alex.put("o.ics", own_series("o-3"))
    mail.clear()
    wed = FRI - dt.timedelta(days=2) + dt.timedelta(weeks=2)
    r = cli("event", "delete", "Jour fixe", "--occurrence", str(wed))
    assert r.code == 0, r
    assert mail.messages() == []
    assert "EXDATE" in alex.get("o.ics")


def test_organizer_cancel_notify_and_delete_quiet(world, cli):
    alex, bob, mail = world
    alex.put("o.ics", own_single("o-4"))
    mail.clear()
    r = cli("event", "cancel", "Kickoff", "--notify")
    assert r.code == 0, r
    assert CAROL in _rcpts(mail.messages(), "CANCEL")
    mail.clear()
    r = cli("event", "delete", "Kickoff")
    assert r.code == 0, r
    assert mail.messages() == []
    assert bob.hrefs()  # colleague keeps the (cancelled) copy: quiet delete tells nobody


def test_organizer_delete_notify_cancels(world, cli):
    alex, _, mail = world
    alex.put("o.ics", own_single("o-5"))
    mail.clear()
    r = cli("event", "delete", "Kickoff", "--notify")
    assert r.code == 0, r
    assert _rcpts(mail.messages(), "CANCEL") == sorted([BOB, CAROL])


def test_create_with_attendees_quiet_then_notify(world, cli):
    _, bob, mail = world
    r = cli("event", "create", "--title", "Planning", "--start", f"{FRI} 15:00", "--attendee", CAROL,
            extra_env={"NEXTCLOUDCALENDAR_ADDRESSES": "alex@example.test"})
    assert r.code == 0, r
    assert mail.messages() == [] and "not invited" in " ".join(r.json["notes"]).lower()
    r = cli("event", "create", "--title", "Planning 2", "--start", f"{FRI} 16:00", "--attendee", CAROL, "--notify")
    assert r.code == 0, r
    assert r.json["mailed"] == [CAROL]
    assert _rcpts(mail.messages(), "REQUEST") == [CAROL]


# ---- import & repair (the 05.11.26 incident) ---------------------------------

def test_import_occurrence_update_mail_gives_one_occurrence(world, cli, tmp_path):
    alex, _, mail = world
    alex.put("incident.ics", invite_series("incident-1"))
    eml = tmp_path / "moved.eml"
    eml.write_text(move_mail("incident-1"))
    r = cli("event", "import", str(eml))
    assert r.code == 0, r
    assert r.json["mailed"] == [] and r.json["method"] == "REQUEST"
    moved = FRI + dt.timedelta(weeks=1)
    lst = cli("event", "list", "--from", str(moved), "--days", "1").json
    assert [(x["start"][11:16], x["end"][11:16], x["myStatus"]) for x in lst] == [("11:30", "11:55", "ACCEPTED")]
    body = alex.get("incident.ics")
    assert f"RECURRENCE-ID:{moved:%Y%m%d}T110000" in body  # floating, like the series
    assert cli("diagnose").json["findings"] == []
    assert mail.messages() == []


def test_diagnose_finds_and_fixes_the_incident(world, cli):
    alex, _, mail = world
    alex.put("incident.ics", broken_incident("incident-2"))
    moved = FRI + dt.timedelta(weeks=1)
    assert cli("event", "list", "--from", str(moved), "--days", "1").json in ([],)  # vanished (EXDATE)
    d = cli("diagnose")
    assert sorted(f["code"] for f in d.json["findings"]) == ["excluded-but-changed", "occurrence-form-mismatch"]
    assert cli("diagnose", "--exit-code").code == 20
    f = cli("diagnose", "--fix")
    assert f.code == 0 and f.json["remaining"] == [], f
    lst = cli("event", "list", "--from", str(moved), "--days", "1").json
    assert [x["start"][11:16] for x in lst] == ["11:30"]
    assert mail.messages() == []


def test_server_refuses_duplicate_uid_in_one_calendar(world):
    """Observed: Nextcloud 409s a second object with the same UID in a calendar, so
    duplicate-uid can only arise ACROSS calendars (covered by the unit tests)."""
    alex, _, _ = world
    alex.put("a.ics", personal("dup-1"))
    import pytest as _p

    with _p.raises(AssertionError, match="409"):
        alex.put("b.ics", personal("dup-1"))


def test_trash_name_clash_is_explained_and_purge_resolves_it(world, cli):
    """Observed on Nextcloud 35: re-creating a file name with the SAME UID silently
    replaces the old trash entry, but reusing a name for a DIFFERENT event and
    deleting it again fails with 403 ("... can't be moved into the trashbin")."""
    alex, _, _ = world
    alex.put("same.ics", personal("same-1"))
    assert cli("event", "delete", "same-1").code == 0
    alex.put("same.ics", personal("same-2"))
    r = cli("event", "delete", "same-2")
    assert r.code == 4 and "trash purge" in r.error["error"], r
    old = next(t for t in cli("trash", "list").json if t["uid"] == "same-1")
    assert cli("trash", "purge", old["id"]).code == 0
    assert cli("event", "delete", "same-2").code == 0


# ---- contract details ----------------------------------------------------------

def test_dry_run_writes_nothing(world, cli):
    alex, _, mail = world
    r = cli("event", "create", "--title", "X", "--start", f"{FRI} 08:00", "--dry-run")
    assert r.code == 0 and r.json["dryRun"] and r.json["request"]["method"] == "PUT"
    assert not alex.hrefs() and mail.messages() == []


def test_ambiguous_title_lists_candidates(world, cli):
    alex, _, _ = world
    alex.put("a.ics", personal("amb-1", FRI, 9))
    alex.put("b.ics", personal("amb-2", FRI, 13))
    r = cli("event", "move", "Dentist", "--by", "+1h")
    assert r.code == 7
    ids = {c["id"] for c in r.error["detail"]["candidates"]}
    assert ids == {"personal/a.ics", "personal/b.ics"}


def test_bad_password_is_exit_4(world, cli):
    r = cli("event", "list", extra_env={"NEXTCLOUDCALENDAR_TOKEN": "wrong"})
    assert r.code == 4 and "app password" in r.error["error"]


def test_auth_login_stores_and_status_reports(stack, tmp_path):
    import subprocess

    from conftest import BIN

    cfg = tmp_path / "cfg"
    # fail.Keyring = "no keyring": exercises the 0600 fallback file end to end.
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "NEXTCLOUDCALENDAR_CONFIG_DIR": str(cfg),
           "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring"}
    p = subprocess.run([BIN, "auth", "login", "--url", stack, "--user", "alex", "--token-stdin", "--timezone", "Europe/Berlin"],
                       input="test-pw-alex-123456\n", capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    import json

    out = json.loads(p.stdout)
    assert out["addresses"] == ["alex@example.test"] and out["defaultCalendar"] == "personal"
    s = json.loads(subprocess.run([BIN, "auth", "status"], capture_output=True, text=True, env=env).stdout)
    assert s["configured"] and s["reachable"] is True
