"""Regressions from the 2026-10-04 ship-review of v0.1.0..v0.2.1."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from brief import scan
from brief.docs import DocError
from brief.gate import check_staged

LOCKED_BAD_YAML = """---
title: Retry: idempotent only
status: active
related_code: ["src/**"]
---
<!-- brief:anchor retry -->
## Retry
Retry idempotent calls only.
"""


def _git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout


def _repo(tmp_path: Path, doc: str) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".brief" / "docs").mkdir(parents=True)
    (tmp_path / ".brief" / "project.yaml").write_text("id: acme\n")
    (tmp_path / ".brief" / "docs" / "retry.md").write_text(doc)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


@pytest.mark.parametrize("bad", [LOCKED_BAD_YAML, "---\nstatus active\n---\n<!-- brief:anchor retry -->\n## Retry\nRetry idempotent calls only.\n"])
def test_unparseable_baseline_fails_closed(tmp_path, bad):
    # Fixing the YAML must not double as an unreviewed rewrite of the rule.
    repo = _repo(tmp_path, bad)
    doc = repo / ".brief" / "docs" / "retry.md"
    doc.write_text(
        '---\ntitle: "Retry: idempotent only"\nstatus: active\nrelated_code: ["src/**"]\n---\n'
        "<!-- brief:anchor retry -->\n## Retry\nRetry everything, always.\n"
    )
    _git(repo, "add", "-A")
    assert any(v.kind == "ratified-edit" for v in check_staged(repo, repo / ".brief"))


def test_check_from_a_subdirectory_sees_root_relative_paths(tmp_path):
    good = LOCKED_BAD_YAML.replace("title: Retry: idempotent only", 'title: "Retry"')
    repo = _repo(tmp_path, good)
    (repo / ".brief" / "docs" / "features.md").write_text(
        "---\nid: features\ntype: features\n---\n<!-- brief:anchor core -->\n## Core\n```yaml\npaths:\n  - \"src/**\"\n```\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "map")
    doc = repo / ".brief" / "docs" / "retry.md"
    doc.write_text(doc.read_text().replace("idempotent calls only", "everything"))
    _git(repo, "add", "-A")
    r = subprocess.run([sys.executable, "-m", "brief", "check"], cwd=repo / "src", capture_output=True, text=True)
    assert r.returncode == 1
    assert "READ-ONLY" in r.stderr  # the ratified edit is caught from a subdir too
    assert "matches no tracked file" not in r.stderr  # and src/** is not a false empty-glob


def test_feature_paths_must_be_globs(tmp_path):
    from brief.features import load_features

    bd = tmp_path / ".brief"
    (bd / "docs").mkdir(parents=True)
    (bd / "docs" / "features.md").write_text(
        "---\nid: features\ntype: features\n---\n<!-- brief:anchor core -->\n## Core\n```yaml\npaths: 5\n```\n"
    )
    with pytest.raises(DocError, match=r"features.md#core: `paths:` must be"):
        load_features(bd)


def test_bad_aliases_is_a_doc_error(tmp_path):
    from brief.versions import load_aliases

    (tmp_path / "aliases.yaml").write_text("a: [unclosed\n")
    with pytest.raises(DocError, match="aliases.yaml: not valid YAML"):
        load_aliases(tmp_path)


def test_nested_agent_dirs_are_tooling(tmp_path):
    f = tmp_path / "apps" / "web" / ".claude" / "agents" / "decision-maker.md"
    f.parent.mkdir(parents=True)
    f.write_text("# decision maker\n")
    m = scan.build_map(tmp_path)
    assert {d.path: d.genre for d in m.docs}["apps/web/.claude/agents/decision-maker.md"] == "agent-tooling"


def test_init_ci_never_downgrades_the_pin(tmp_path):
    from brief.init import init_vault
    from brief.templates import CI_WORKFLOW

    init_vault(tmp_path, ci=True)
    wf = tmp_path / ".github" / "workflows" / "brief.yml"
    newer = CI_WORKFLOW.replace(CI_WORKFLOW.split("brief@")[1].split(" ")[0], "v99.0.0")
    wf.write_text(newer)
    assert any("pins a newer brief" in a for a in init_vault(tmp_path, ci=True))
    assert wf.read_text() == newer


def test_update_check_ignores_prerelease_tags(tmp_path):
    from brief import __version__
    from brief.templates import CI_WORKFLOW

    script = CI_WORKFLOW.split("run: |\n", 1)[1]
    fake = tmp_path / "bin" / "git"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/sh\nprintf 'x\\trefs/tags/v%s\\nx\\trefs/tags/v99.0.0rc1\\n' " + __version__ + "\n"
    )
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake.parent}:{os.environ['PATH']}"}
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout == ""
