"""How a new brief reaches a governed repo: UPGRADING entries, drift warning, skill refresh."""
import re
from pathlib import Path

from brief import __version__
from brief.init import _install_skills, version_drift
from brief.templates import CI_WORKFLOW

ROOT = Path(__file__).resolve().parents[1]


def test_every_release_has_an_upgrading_entry():
    text = (ROOT / "UPGRADING.md").read_text()
    assert f"## v{__version__}\n" in text, f"add a '## v{__version__}' entry to UPGRADING.md"
    entry = text.split(f"## v{__version__}\n", 1)[1].split("\n## ", 1)[0]
    assert "**Changed:**" in entry and "**Do:**" in entry


def test_drift_warning_only_when_the_pin_differs(tmp_path):
    assert version_drift(tmp_path) is None  # nothing pinned
    wf = tmp_path / ".github" / "workflows" / "brief.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text(CI_WORKFLOW)
    assert version_drift(tmp_path) is None  # pinned to this version
    wf.write_text(re.sub(r"@v[\d.]+", "@v0.1.0", CI_WORKFLOW))
    warning = version_drift(tmp_path)
    assert "v0.1.0" in warning and "brief@v0.1.0 brief check" in warning


def test_skill_refresh_replaces_and_drops_only_brief_skills(tmp_path):
    skills = tmp_path / ".claude" / "skills"
    (skills / "brief-retired").mkdir(parents=True)
    (skills / "brief-retired" / "SKILL.md").write_text("old")
    (skills / "brief-amend").mkdir()
    (skills / "brief-amend" / "stale-extra.md").write_text("old")
    (skills / "mine").mkdir()
    (skills / "mine" / "SKILL.md").write_text("user's own")
    actions = []
    _install_skills(tmp_path, actions)
    assert not (skills / "brief-retired").exists()
    assert not (skills / "brief-amend" / "stale-extra.md").exists()
    assert (skills / "brief-amend" / "SKILL.md").exists()
    assert (skills / "mine" / "SKILL.md").read_text() == "user's own"
