"""Config: absent, malformed, env overlay, env-only profile. Hermetic."""

from __future__ import annotations

import pytest

from nextcloudcalendar.config import Config, Profile, config_path
from nextcloudcalendar.errors import ConfigError


def test_absent_config_is_fine():
    cfg = Config.load()
    assert cfg.profiles == {} and cfg.context == {}


def test_no_profile_and_no_env_is_a_config_error_naming_the_fix():
    with pytest.raises(ConfigError) as ei:
        Config.load().resolve()
    assert ei.value.exit_code == 3
    assert "auth login" in ei.value.message and "NEXTCLOUDCALENDAR_URL" in ei.value.message


def test_malformed_config_names_the_path():
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text('{"profiles": {"default": "not-a-dict"}}')
    with pytest.raises(ConfigError) as ei:
        Config.load()
    assert str(config_path()) in ei.value.message


def test_env_only_profile_needs_no_file(monkeypatch):
    monkeypatch.setenv("NEXTCLOUDCALENDAR_URL", "https://cloud.example.test/")
    monkeypatch.setenv("NEXTCLOUDCALENDAR_USER", "alex")
    monkeypatch.setenv("NEXTCLOUDCALENDAR_ADDRESSES", "A@Example.test, b@example.test")
    p = Config.load().resolve()
    assert p.base_url == "https://cloud.example.test"
    assert p.username == "alex"
    assert p.addresses == ["a@example.test", "b@example.test"]


def test_nextcloud_aliases_work(monkeypatch):
    monkeypatch.setenv("NEXTCLOUD_URL", "https://cloud.example.test")
    monkeypatch.setenv("NEXTCLOUD_USER", "bob")
    p = Config.load().resolve()
    assert (p.base_url, p.username) == ("https://cloud.example.test", "bob")


def test_env_overlays_a_saved_profile_and_keeps_verify_ssl(monkeypatch):
    cfg = Config.load()
    cfg.upsert_profile(Profile(name="default", base_url="https://saved.example.test", username="alex",
                               addresses=["alex@example.test"], timezone="Europe/Berlin", verify_ssl=False))
    cfg.save()
    monkeypatch.setenv("NEXTCLOUDCALENDAR_URL", "https://override.example.test")
    monkeypatch.setenv("NEXTCLOUDCALENDAR_ADDRESSES", "alias@example.test")
    p = Config.load().resolve()
    assert p.base_url == "https://override.example.test"
    assert p.verify_ssl is False
    assert p.addresses == ["alex@example.test", "alias@example.test"]
    assert p.timezone == "Europe/Berlin"


def test_profile_env_selects_the_profile(monkeypatch):
    cfg = Config.load()
    cfg.upsert_profile(Profile(name="work", base_url="https://work.example.test", username="w"))
    cfg.upsert_profile(Profile(name="home", base_url="https://home.example.test", username="h"))
    cfg.save()
    monkeypatch.setenv("NEXTCLOUDCALENDAR_PROFILE", "work")
    assert Config.load().resolve().username == "w"


def test_round_trip_keeps_context_per_profile():
    cfg = Config.load()
    cfg.upsert_profile(Profile(name="default", base_url="https://x.example.test", username="u"))
    cfg.contexts["default"] = {"calendar": "personal"}
    cfg.save()
    again = Config.load()
    assert again.context == {"calendar": "personal"}
