"""The per-invocation DI container."""

from __future__ import annotations

import os
import sys

from agentcli import Emitter, OutputFormat
from agentcli.errors import ConfigError

from . import __version__
from .client import Client
from .config import Config, system_timezone
from .dav import Dav
from .ical import resolve_zone
from .scheduling import Writer
from .spec import SPEC, app_password_url, credentials


class AppContext:
    def __init__(self, *, output: OutputFormat | None = None, color: bool = True, interactive: bool = False) -> None:
        self.config = Config.load()
        self.color = color
        self.interactive = interactive
        self.output = self._resolve_format(output)
        self.emitter = Emitter(
            self.output,
            color=color,
            fields=self._resolve_fields(),
            stream=os.environ.get("NEXTCLOUDCALENDAR_STREAM") == "1",
        )
        self._client: Client | None = None
        self._dav: Dav | None = None
        self._profile = None
        if self.interactive:
            self._maybe_offer_claude_skill()

    # ---- format ------------------------------------------------------
    def _resolve_format(self, explicit: OutputFormat | None) -> OutputFormat:
        if explicit is not None:
            return explicit
        cli_fmt = os.environ.get("NEXTCLOUDCALENDAR_CLI_FORMAT")
        if cli_fmt:
            return OutputFormat.coerce(cli_fmt)  # raises -> caught by main(), exit 1
        for src in (SPEC.getenv("FORMAT"), self.config.default_format):
            if src:
                try:
                    return OutputFormat.coerce(src)
                except ValueError:
                    pass
        if self.interactive:
            chosen = self._ask_default_format()
            if chosen:
                return chosen
        return OutputFormat.json

    def _ask_default_format(self) -> OutputFormat | None:
        try:
            sys.stderr.write(
                "\nFirst run — default output format?\n"
                "  json  (default; best for agents)   table   markdown\n"
                "Choice [json]: "
            )
            sys.stderr.flush()
            ans = (sys.stdin.readline() or "").strip().lower()
        except Exception:
            return None
        fmt = OutputFormat.json
        if ans:
            try:
                fmt = OutputFormat.coerce(ans)
            except ValueError:
                fmt = OutputFormat.json
        try:
            self.config.default_format = fmt.value
            self.config.save()
            sys.stderr.write("Saved. Change it: `nextcloud-calendar settings set-format <fmt>`\n\n")
        except Exception:
            pass
        return fmt

    def _maybe_offer_claude_skill(self) -> None:
        try:
            from .commands import install

            if self.config.claude_prompted:
                return
            if not install.claude_available() or install.skill_installed():
                return
            self.config.claude_prompted = True
            self.config.save()
            sys.stderr.write(
                "\nClaude Code is installed here. Register `nextcloud-calendar` as a skill, so Claude\n"
                "uses it when you mention a Nextcloud calendar or appointments (Termine)?\n"
                "  writes ~/.claude/skills/nextcloud-calendar/SKILL.md — undo with "
                "`nextcloud-calendar install claude --uninstall`\n"
                "Install it? [y/N]: "
            )
            sys.stderr.flush()
            ans = (sys.stdin.readline() or "").strip().lower()
            if ans not in ("y", "yes"):
                sys.stderr.write("Skipped — change your mind any time: `nextcloud-calendar install claude`\n\n")
                return
            path = install.write_skill()
            sys.stderr.write(f"Installed {path}\nStart a new Claude session to pick it up.\n\n")
        except Exception:
            pass

    @staticmethod
    def _resolve_fields() -> list[str] | None:
        raw = os.environ.get("NEXTCLOUDCALENDAR_CLI_FIELDS")
        if not raw:
            return None
        return [f.strip() for f in raw.split(",") if f.strip()]

    # ---- client & domain services --------------------------------------
    def profile(self):
        if self._profile is None:
            self._profile = self.config.resolve()
        return self._profile

    def client(self) -> Client:
        if self._client is None:
            prof = self.profile()
            token = credentials.get_token(self.config.active_profile_name())
            if not token or not prof.username:
                raise ConfigError(
                    "no login. Run `nextcloud-calendar auth login`, or set NEXTCLOUDCALENDAR_URL + NEXTCLOUDCALENDAR_USER + NEXTCLOUDCALENDAR_TOKEN "
                    f"(create an app password at {app_password_url(prof.base_url or 'https://<your-nextcloud>')})."
                )
            self._client = Client(
                prof.base_url,
                prof.username,
                token,
                verify_ssl=prof.verify_ssl,
                dry_run=os.environ.get("NEXTCLOUDCALENDAR_DRY_RUN") == "1",
                user_agent=f"agent-tool-nextcloud-calendar-cli/{__version__}",
            )
        return self._client

    def dav(self) -> Dav:
        if self._dav is None:
            self._dav = Dav(self.client())
        return self._dav

    @property
    def local(self):
        """The zone floating times are read in and output is shown in."""
        return resolve_zone(self.profile().timezone or system_timezone())

    def me(self) -> list[str]:
        """Every address that means "me": configured ones + what the server reports."""
        addrs = [a.lower() for a in self.profile().addresses]
        try:
            for a in self.dav().principal().get("addresses", []):
                if a not in addrs:
                    addrs.append(a)
        except Exception:
            pass
        return addrs

    def writer(self) -> Writer:
        return Writer(self.dav(), self.me(), self.local)
