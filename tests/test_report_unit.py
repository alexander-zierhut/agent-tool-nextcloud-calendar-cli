"""`report` must work offline and name THIS tool's repo.

Same property as the guide: an installed binary with no README or AGENTS.md
beside it still has to tell a user where a problem is reported. So `report`
reaches no network, needs no token, and cannot fail on config, and it must name
this tool's OWN repo, not a sibling's (a copy-paste slug is the obvious bug).

Hermetic: introspection only.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from nextcloudcalendar import __version__
from nextcloudcalendar.cli import app


def test_report_runs_offline_and_names_this_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXTCLOUDCALENDAR_CONFIG_DIR", str(tmp_path / "does-not-exist"))
    monkeypatch.delenv("NEXTCLOUDCALENDAR_TOKEN", raising=False)

    result = CliRunner().invoke(app, ["report"])
    assert result.exit_code == 0, result.output

    data = json.loads(result.stdout)
    assert data["repo"] == "alexander-zierhut/agent-tool-nextcloud-calendar-cli"
    assert data["version"] == __version__
    assert data["issues"].endswith("/agent-tool-nextcloud-calendar-cli/issues")
    assert "/issues/new?" in data["newIssue"]
    assert __version__ in data["newIssue"]
