"""Non-secret configuration: connection profiles and settings.

The app password is NOT here — it lives in the OS keyring (see `spec.credentials`).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentcli.errors import ConfigError

from .spec import SPEC, credentials

DEFAULT_PROFILE = "default"


def config_dir() -> Path:
    return SPEC.config_dir()


def config_path() -> Path:
    return SPEC.config_file()


def system_timezone() -> str:
    """The IANA name of the machine's zone; floating times are read in it."""
    tz = os.environ.get("TZ")
    if tz and "/" in tz:
        return tz.lstrip(":")
    try:
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        name = Path("/etc/timezone").read_text().strip()
        if name:
            return name
    except OSError:
        pass
    return "UTC"


@dataclass
class Profile:
    name: str
    base_url: str = ""
    username: str | None = None
    # Every address that means "me" in ORGANIZER/ATTENDEE lines (mailto:, lower-case,
    # without the scheme). Discovered from calendar-user-address-set at login; add
    # aliases with `auth login --address`.
    addresses: list[str] = field(default_factory=list)
    default_calendar: str | None = None
    timezone: str | None = None
    verify_ssl: bool = True


@dataclass
class Config:
    current_profile: str = DEFAULT_PROFILE
    profiles: dict[str, Profile] = field(default_factory=dict)

    default_format: str | None = None     # None = never chosen -> ask once
    claude_prompted: bool = False
    contexts: dict[str, dict] = field(default_factory=dict)

    # ---- persistence -------------------------------------------------
    @classmethod
    def load(cls) -> Config:
        path = config_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
            profiles = {
                name: Profile(
                    name=name,
                    base_url=p.get("base_url", ""),
                    username=p.get("username"),
                    addresses=list(p.get("addresses") or []),
                    default_calendar=p.get("default_calendar"),
                    timezone=p.get("timezone"),
                    verify_ssl=p.get("verify_ssl", True),
                )
                for name, p in raw.get("profiles", {}).items()
            }
            return cls(
                current_profile=raw.get("current_profile", DEFAULT_PROFILE),
                profiles=profiles,
                default_format=raw.get("default_format"),
                claude_prompted=bool(raw.get("claude_prompted", False)),
                contexts=raw.get("contexts") or {},
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ConfigError(f"malformed config at {path}: {exc}") from exc

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "current_profile": self.current_profile,
            "default_format": self.default_format,
            "claude_prompted": self.claude_prompted,
            "contexts": self.contexts,
            "profiles": {
                name: {
                    "base_url": p.base_url,
                    "username": p.username,
                    "addresses": p.addresses,
                    "default_calendar": p.default_calendar,
                    "timezone": p.timezone,
                    "verify_ssl": p.verify_ssl,
                }
                for name, p in self.profiles.items()
            },
        }
        path.write_text(json.dumps(data, indent=2) + "\n")

    # ---- resolution --------------------------------------------------
    def active_profile_name(self) -> str:
        return SPEC.getenv("PROFILE") or self.current_profile

    @staticmethod
    def _env_url() -> str | None:
        return SPEC.getenv("URL") or os.environ.get("NEXTCLOUD_URL")

    @staticmethod
    def _env_user() -> str | None:
        return SPEC.getenv("USER") or os.environ.get("NEXTCLOUD_USER")

    def resolve(self) -> Profile:
        """Profile precedence: saved profile, with $NEXTCLOUDCALENDAR_URL / $NEXTCLOUDCALENDAR_USER overlaid.

        No saved profile + $NEXTCLOUDCALENDAR_URL + $NEXTCLOUDCALENDAR_USER + $NEXTCLOUDCALENDAR_TOKEN is the complete
        headless story (CI, tests, containers): no config file, no login step.
        """
        name = self.active_profile_name()
        env_url, env_user = self._env_url(), self._env_user()
        env_tz = SPEC.getenv("TIMEZONE")
        env_addr = [a.strip().lower() for a in (SPEC.getenv("ADDRESSES") or "").split(",") if a.strip()]
        prof = self.profiles.get(name)
        if prof is None:
            if env_url and env_user:
                return Profile(name=name, base_url=env_url.rstrip("/"), username=env_user, addresses=env_addr, timezone=env_tz)
            raise ConfigError(
                f"no profile '{name}' configured. Run `nextcloud-calendar auth login`, "
                "or set NEXTCLOUDCALENDAR_URL + NEXTCLOUDCALENDAR_USER + NEXTCLOUDCALENDAR_TOKEN."
            )
        return Profile(
            name=prof.name,
            base_url=(env_url or prof.base_url).rstrip("/"),
            username=env_user or prof.username,
            addresses=list(dict.fromkeys([*prof.addresses, *env_addr])),
            default_calendar=prof.default_calendar,
            timezone=env_tz or prof.timezone,
            verify_ssl=prof.verify_ssl,
        )

    def upsert_profile(self, prof: Profile, make_current: bool = True) -> None:
        self.profiles[prof.name] = prof
        if make_current:
            self.current_profile = prof.name

    @property
    def context(self) -> dict:
        return self.contexts.get(self.active_profile_name()) or {}


__all__ = ["Config", "Profile", "config_dir", "config_path", "credentials", "system_timezone"]
