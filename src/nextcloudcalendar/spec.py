"""This tool's identity, and the shared services derived from it."""

from __future__ import annotations

from agentcli import AppSpec, Credentials

SPEC = AppSpec(
    name="nextcloud-calendar",
    env_prefix="NEXTCLOUDCALENDAR",
    # Honoured AFTER NEXTCLOUDCALENDAR_TOKEN. Nextcloud calls the credential an "app password".
    token_env_aliases=("NEXTCLOUD_APP_PASSWORD",),
    repo="alexander-zierhut/agent-tool-nextcloud-calendar-cli",
)

credentials = Credentials(SPEC)


def app_password_url(server: str) -> str:
    """Where a human creates an app password (Settings -> Security)."""
    return server.rstrip("/") + "/index.php/settings/user/security"
