"""Nextcloud-calendar additions to the shared exit-code taxonomy.

0-7 are the shared family contract (0 ok · 1 generic · 3 config · 4 auth ·
5 not-found · 6 conflict · 7 validation · 130 SIGINT). 8+ are this tool's own.
"""

from __future__ import annotations

from agentcli.errors import (  # noqa: F401  (re-exported for command modules)
    ApiError,
    AuthError,
    ConfigError,
    ConflictError,
    DryRun,
    NotFoundError,
    OpError,
    ValidationError,
)


class SchedulingRefused(OpError):
    """The write cannot be done with the requested notification behaviour.

    Exit **8**. Observed on Nextcloud 35: some changes ALWAYS make the server mail
    other people (adding a changed occurrence to a meeting you organise sends a
    REQUEST to every attendee), and some notifications are impossible (an attendee
    cannot tell the organizer about a new time through the server). Rather than
    silently mailing people, or silently not mailing them, the tool refuses and
    says which flag gets the behaviour the caller can actually have.
    """

    exit_code = 8

