"""Shared fixtures.

Two tiers, like the sibling tools:
  * hermetic (default) — pure logic and fakes; no network, no account.
  * integration (`-m integration`) — the real `nextcloud-calendar` binary against
    the local docker stack (Nextcloud 35 + Mailpit, `make up`). Mailpit is the
    point: every test asserts WHO the server e-mailed, not just what got stored.

Write-safety interlock: integration tests refuse any server that is not on
loopback. They create and delete events freely; that must never reach a real
calendar. NEXTCLOUDCALENDAR_REQUIRE_INTEGRATION=1 (CI) turns "stack not running" from a
skip into a failure, so a silently skipped live tier cannot look green.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_LEAKY = (
    "NEXTCLOUDCALENDAR_URL", "NEXTCLOUDCALENDAR_USER", "NEXTCLOUDCALENDAR_TOKEN", "NEXTCLOUDCALENDAR_PROFILE", "NEXTCLOUDCALENDAR_TIMEZONE", "NEXTCLOUDCALENDAR_ADDRESSES",
    "NEXTCLOUDCALENDAR_FORMAT", "NEXTCLOUDCALENDAR_CLI_FORMAT", "NEXTCLOUDCALENDAR_CLI_FIELDS", "NEXTCLOUDCALENDAR_DRY_RUN", "NEXTCLOUDCALENDAR_STREAM",
    "NEXTCLOUDCALENDAR_NO_CONTEXT", "NEXTCLOUD_URL", "NEXTCLOUD_USER", "NEXTCLOUD_APP_PASSWORD",
)

# Snapshot BEFORE the autouse fixture strips the environment.
LIVE_ENV = dict(os.environ)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXTCLOUDCALENDAR_CONFIG_DIR", str(tmp_path / "config"))
    for v in _LEAKY:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    yield


# ---- integration tier --------------------------------------------------------

NC_URL = LIVE_ENV.get("NEXTCLOUDCALENDAR_TEST_URL", "http://127.0.0.1:8089")
MAILPIT = LIVE_ENV.get("NEXTCLOUDCALENDAR_TEST_MAILPIT", "http://127.0.0.1:8025")
BIN = str(Path(sys.executable).with_name("nextcloud-calendar"))


def _assert_loopback(url: str) -> None:
    """The write-safety interlock. No override on purpose: these tests create and
    delete events freely, and the stack's credentials are synthetic, so a
    non-loopback URL can only be a mistake. Proven by tests/test_interlock_unit.py."""
    host = urlsplit(url).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(f"refusing to run write tests against {url}: not loopback")


@pytest.fixture(scope="session")
def stack():
    import httpx

    _assert_loopback(NC_URL)
    try:
        ok = httpx.get(f"{NC_URL}/status.php", timeout=3).json().get("installed")
        httpx.get(f"{MAILPIT}/api/v1/messages", timeout=3).raise_for_status()
        httpx.request("PROPFIND", f"{NC_URL}/remote.php/dav/", auth=("alex", "test-pw-alex-123456"),
                      headers={"Depth": "0"}, timeout=5).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        ok = False
        reason = f"local stack not reachable ({exc}); run `make up`"
    else:
        reason = "local stack not installed/seeded; run `make up`"
    if not ok:
        if LIVE_ENV.get("NEXTCLOUDCALENDAR_REQUIRE_INTEGRATION") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    return NC_URL


class Mail:
    def __init__(self) -> None:
        import httpx

        self.h = httpx.Client(base_url=MAILPIT, timeout=10)

    def clear(self) -> None:
        self.h.delete("/api/v1/messages")

    def messages(self, settle: float = 1.0) -> list[dict]:
        """[{to: [...], method: 'REQUEST'|'REPLY'|'CANCEL'|None, subject}] — waits briefly for stragglers."""
        time.sleep(settle)
        out = []
        for m in self.h.get("/api/v1/messages").json().get("messages", []):
            full = self.h.get(f"/api/v1/message/{m['ID']}").json()
            method = None
            for a in full.get("Attachments", []) + full.get("Inline", []):
                if "calendar" in a.get("ContentType", ""):
                    raw = self.h.get(f"/api/v1/message/{m['ID']}/part/{a['PartID']}").text
                    method = next((ln.split(":", 1)[1].strip() for ln in raw.splitlines() if ln.startswith("METHOD")), None)
            out.append({"to": sorted(t["Address"] for t in m["To"]), "method": method, "subject": m["Subject"]})
        return out


class Dav:
    """Direct DAV access for seeding and inspecting — deliberately NOT the CLI."""

    def __init__(self, user: str) -> None:
        import httpx

        self.user = user
        self.h = httpx.Client(base_url=NC_URL, auth=(user, f"test-pw-{user}-123456"), timeout=30)
        self.cal = f"/remote.php/dav/calendars/{user}/personal/"

    def hrefs(self) -> list[str]:
        import re

        r = self.h.request("PROPFIND", self.cal, headers={"Depth": "1"})
        return [h for h in re.findall(r"<d:href>([^<]+)</d:href>", r.text) if h.endswith(".ics")]

    def wipe(self) -> None:
        self.purge_trash()
        for h in self.hrefs():
            self.h.delete(h, headers={"Schedule-Reply": "F"})
        self.purge_trash()

    def purge_trash(self) -> None:
        import re

        body = ('<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/></d:prop>'
                '<c:filter><c:comp-filter name="VCALENDAR"/></c:filter></c:calendar-query>')
        r = self.h.request("REPORT", f"/remote.php/dav/calendars/{self.user}/trashbin/objects/", content=body,
                           headers={"Depth": "1", "Content-Type": "application/xml"})
        for h in re.findall(r"<d:href>([^<]+\.ics)</d:href>", r.text):
            self.h.delete(h)

    def put(self, name: str, ics: str) -> None:
        r = self.h.put(self.cal + name, content=ics.replace("\r\n", "\n").replace("\n", "\r\n").encode(),
                       headers={"Content-Type": "text/calendar; charset=utf-8"})
        assert r.status_code in (201, 204), r.text

    def get(self, name: str) -> str:
        return self.h.get(self.cal + name).text.replace("\r\n ", "").replace("\r\n", "\n")

    def bodies(self) -> list[str]:
        return [self.h.get(h).text.replace("\r\n ", "").replace("\r\n", "\n") for h in self.hrefs()]


@pytest.fixture
def env(stack, tmp_path):
    e = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "NEXTCLOUDCALENDAR_URL": stack, "NEXTCLOUDCALENDAR_USER": "alex", "NEXTCLOUDCALENDAR_TOKEN": "test-pw-alex-123456",
        "NEXTCLOUDCALENDAR_TIMEZONE": "Europe/Berlin", "NEXTCLOUDCALENDAR_CONFIG_DIR": str(tmp_path / "cfg"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    return e


@pytest.fixture
def world(stack):
    """Clean calendars for alex and bob, empty mailbox."""
    alex, bob, mail = Dav("alex"), Dav("bob"), Mail()
    alex.wipe()
    bob.wipe()
    mail.clear()
    yield alex, bob, mail
    alex.wipe()
    bob.wipe()


class Result:
    def __init__(self, proc: subprocess.CompletedProcess) -> None:
        self.code = proc.returncode
        self.stdout, self.stderr = proc.stdout, proc.stderr
        try:
            self.json = json.loads(proc.stdout) if proc.stdout.strip() else None
        except ValueError:
            self.json = None
        try:
            self.error = json.loads(proc.stderr) if proc.stderr.strip().startswith("{") else None
        except ValueError:
            self.error = None

    def __repr__(self) -> str:
        return f"<exit {self.code} stdout={self.stdout[:400]!r} stderr={self.stderr[:400]!r}>"


@pytest.fixture
def cli(env):
    def run(*args: str, extra_env: dict | None = None) -> Result:
        proc = subprocess.run([BIN, *args], capture_output=True, text=True, env={**env, **(extra_env or {})}, timeout=120)
        return Result(proc)
    return run
