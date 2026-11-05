"""Reserved global flags + guide/skill honesty — hermetic, introspection only."""

from __future__ import annotations

import re

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from nextcloudcalendar.cli import _BOOL_FLAGS, _FIELDS_FLAGS, _FORMAT_FLAGS, _pop_globals, app

RESERVED = set(_FORMAT_FLAGS) | set(_FIELDS_FLAGS) | set(_BOOL_FLAGS)


def _walk(cmd, path=""):
    subs = getattr(cmd, "commands", None)
    if subs:
        for name, sub in subs.items():
            yield from _walk(sub, f"{path} {name}".strip())
    else:
        yield path, cmd


def _leaves():
    return list(_walk(get_command(app)))


def test_the_tree_has_commands():
    assert len(_leaves()) > 15


def test_no_command_declares_a_reserved_global():
    offenders = []
    for path, cmd in _leaves():
        if not path:
            continue
        for p in cmd.params:
            if getattr(p, "param_type_name", "") != "option":
                continue
            clash = sorted(set(p.opts) & RESERVED)
            if clash:
                offenders.append(f"  `nextcloud-calendar {path}` declares {clash}")
    assert not offenders, "reserved globals can never be received:\n" + "\n".join(offenders)


def test_file_outputs_use_out_not_output():
    """--output is a reserved format flag; any file destination must be --out."""
    for path, cmd in _leaves():
        opts = {o for p in cmd.params for o in getattr(p, "opts", [])}
        assert "--output" not in opts, f"`nextcloud-calendar {path}` uses --output (reserved); use --out"


# ---- _pop_globals ----------------------------------------------------

def test_pops_format_from_anywhere():
    for argv in (["-o", "table", "diagnose"], ["diagnose", "-o", "table"]):
        fmt, _f, _b, rest = _pop_globals(argv)
        assert fmt == "table" and rest == ["diagnose"]


def test_pops_dry_run():
    _f, _fl, bools, rest = _pop_globals(["event", "create", "--dry-run"])
    assert "dry-run" in bools and rest == ["event", "create"]


def test_double_dash_stops_parsing():
    fmt, _f, _b, rest = _pop_globals(["raw", "get", "--", "-o", "x"])
    assert fmt is None and rest == ["raw", "get", "--", "-o", "x"]


# ---- guide honesty ---------------------------------------------------
#
# Every `nextcloud-calendar X Y` named in the guide or SKILL.md must resolve
# against the REAL tree: X a leaf or group, and if X is a group, Y one of its
# subcommands (alternations like `list|get` checked one by one). `guide Y` must
# name a real topic. Lenient checks pass vacuously when docs drift; this one
# does not.

_INVOCATION = re.compile(r"\bnextcloud-calendar[ \t]+([a-z][\w-]*)(?:[ \t]+([a-z][\w|-]*))?")


def _doc_texts():
    from nextcloudcalendar.commands import guide as G
    from nextcloudcalendar.commands import install as I

    return {"guide": G.OVERVIEW + "\n".join(G.TOPICS.values()), "SKILL.md": I.SKILL_MD}


def _unresolved(text: str) -> list[str]:
    from nextcloudcalendar.commands import guide as G

    real = {p for p, _ in _leaves() if p}
    groups = {p.split()[0] for p in real if " " in p}
    leaves = {p for p in real if " " not in p}
    broken = []
    hits = 0
    for m in _INVOCATION.finditer(text):
        hits += 1
        first, second = m.group(1), m.group(2)
        if first == "guide":
            for t in (second or "").split("|"):
                if t and t not in G.TOPICS and t not in ("topics", "list"):
                    broken.append(f"guide {t}")
            continue
        if first in leaves:
            continue
        if first not in groups:
            broken.append(first)
            continue
        if second:
            for sub in second.split("|"):
                if sub and f"{first} {sub}" not in real:
                    broken.append(f"{first} {sub}")
    assert hits > 5, "the invocation regex matched almost nothing; it is probably stale"
    return broken


@pytest.mark.parametrize("doc", ["guide", "SKILL.md"])
def test_docs_name_only_real_commands(doc):
    broken = _unresolved(_doc_texts()[doc])
    assert not broken, f"{doc} names nonexistent commands/topics: {sorted(set(broken))}"


def test_the_resolver_catches_a_typo():
    assert _unresolved("nextcloud-calendar event moev x\n" * 6) == ["event moev"] * 6


def test_guide_has_a_gotchas_topic():
    from nextcloudcalendar.commands import guide as G

    assert "gotchas" in G.TOPICS


def test_every_topic_renders():
    from nextcloudcalendar.commands import guide as G

    for topic, body in G.TOPICS.items():
        assert len(body.strip()) > 40, topic
        r = CliRunner().invoke(app, ["guide", topic])
        assert r.exit_code == 0 and r.stdout.strip(), topic


def test_unknown_topic_exits_2_and_lists_the_real_topics():
    from nextcloudcalendar.commands import guide as G

    r = CliRunner().invoke(app, ["guide", "no-such-topic"])
    assert r.exit_code == 2
    assert all(t in r.output for t in G.TOPICS)


def test_guide_needs_no_config(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXTCLOUDCALENDAR_CONFIG_DIR", str(tmp_path / "nope"))
    monkeypatch.delenv("NEXTCLOUDCALENDAR_TOKEN", raising=False)
    monkeypatch.delenv("NEXTCLOUDCALENDAR_URL", raising=False)
    r = CliRunner().invoke(app, ["guide"])
    assert r.exit_code == 0 and "nextcloud-calendar" in r.stdout


def test_every_topic_named_in_the_overview_exists():
    from nextcloudcalendar.commands import guide as G

    line = next(ln for ln in G.OVERVIEW.splitlines() if ln.startswith("TOPICS:"))
    named = [t.strip() for t in line.split(":", 1)[1].split("·")]
    assert set(named) == set(G.TOPICS)


def test_guide_states_the_exit_codes_the_code_raises():
    from nextcloudcalendar.commands import guide as G
    from nextcloudcalendar.errors import SchedulingRefused

    assert f"{SchedulingRefused.exit_code} scheduling refused" in G.OVERVIEW
    assert "exit 20" in G.OVERVIEW


def test_guide_names_the_token_env_var():
    from nextcloudcalendar.commands import guide as G
    from nextcloudcalendar.spec import SPEC

    assert SPEC.env("TOKEN") in G.OVERVIEW


def test_output_topic_states_the_out_rule():
    from nextcloudcalendar.commands import guide as G

    assert "--out" in G.TOPICS["output"] and "RESERVED" in G.TOPICS["output"]


def test_context_topic_carries_the_hazard_sentence():
    from nextcloudcalendar.commands import guide as G

    assert "context is IMPLICIT state that changes command behaviour" in G.TOPICS["context"]


def test_skill_md_shape():
    from nextcloudcalendar.commands import install as I

    md = I.SKILL_MD
    assert md.startswith("---\nname: nextcloud-calendar\n")
    assert len(md.splitlines()) < 500
    assert "nextcloud-calendar guide" in md
    assert "## Reporting a problem" in md


def test_skill_triggers_are_anchored_to_the_product():
    """Bare verbs ("verschieb", "sag ab") over-fire; every trigger sentence must
    carry the product or an appointment noun."""
    from nextcloudcalendar.commands import install as I

    desc = I.SKILL_MD.split("description:", 1)[1].split("\n---", 1)[0]
    assert desc.strip().startswith(">-\n  Work with the user's Nextcloud calendar")
    trig = " ".join(desc.split()).split("Use this whenever", 1)[1]
    assert "Nextcloud" in trig
    for verb in ("verschieb", "sag", "verlänger", "nimm"):
        quoted = re.findall(r'"([^"]*%s[^"]*)"' % verb, trig)
        assert quoted, verb
        assert all(re.search(r"Termin|Meeting|Besprechung|Einladung", q) for q in quoted), quoted


def test_context_keys_are_real_options():
    """KNOWN_KEYS must be the dest of a real OPTION somewhere, or `context set` silently no-ops."""
    from nextcloudcalendar.commands.context import KNOWN_KEYS

    opts = {p.name for _, cmd in _leaves() for p in cmd.params if getattr(p, "param_type_name", "") == "option"}
    assert set(KNOWN_KEYS) <= opts


def test_context_never_fills_arguments():
    from nextcloudcalendar.cli import _context_default_map

    dm = _context_default_map(get_command(app), {"calendar": "work", "ref": "x"}, skip=set())
    assert dm["event"]["list"] == {"calendar": "work"}
    assert all("ref" not in v for v in dm["event"].values())


def test_guide_runs_without_any_environment(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    exe = str(Path(sys.executable).with_name("nextcloud-calendar"))
    p = subprocess.run([exe, "guide"], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "nohome"), "NEXTCLOUDCALENDAR_CONFIG_DIR": str(tmp_path / "nope")})
    assert p.returncode == 0 and "OUTPUT CONTRACT" in p.stdout
