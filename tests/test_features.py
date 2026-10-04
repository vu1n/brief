import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from brief import doctor
from brief.cli import app
from brief.features import load_features, touched
from brief.gate import check
from brief.resolve import resolve

MAP = """---
id: features
type: features
title: Feature map
---

# Feature map

<!-- brief:anchor search -->
## Search

```yaml
paths:
  - "src/search/**"
  - "cli/search.py"
```

Find notes by title or body.

### Gotchas
- Results are debounced.

<!-- brief:anchor store -->
## Store (internal)

```yaml
paths: "src/store/**"
```

### Gotchas
- Writes are not atomic.
"""

# built, not literal: brief's own `brief check` would treat a literal ref here as a code ref
SEARCH_REF = "doc:" + "//acme/features@latest#search"

ACTIVE = """---
id: adr-search
status: active
related_code:
  - "src/search/**"
---

<!-- brief:anchor search-rule -->
## rule
"""


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path, feature_map: str = MAP) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    write(tmp_path / ".brief" / "project.yaml", "id: acme\n")
    write(tmp_path / ".brief" / "docs" / "features.md", feature_map)
    write(tmp_path / "src" / "search" / "index.py", "x = 1\n")
    write(tmp_path / "cli" / "search.py", "x = 1\n")
    write(tmp_path / "src" / "store" / "db.py", "x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_load_features(tmp_path):
    bd = _repo(tmp_path) / ".brief"
    feats = {f.feature_id: f for f in load_features(bd)}
    assert set(feats) == {"search", "store"}
    assert feats["search"].paths == ["src/search/**", "cli/search.py"]
    assert feats["store"].paths == ["src/store/**"]  # a bare string is one glob
    assert feats["search"].title == "Search"
    assert feats["search"].ref == SEARCH_REF


def test_feature_ref_resolves_to_section_with_gotchas(tmp_path):
    bd = _repo(tmp_path) / ".brief"
    r = resolve(SEARCH_REF, bd)
    assert "### Gotchas" in r.body and "Store" not in r.body


def test_only_feature_maps_yield_features(tmp_path):
    repo = _repo(tmp_path)
    write(repo / ".brief" / "docs" / "adr-search.md", ACTIVE)
    assert {f.doc_id for f in load_features(repo / ".brief")} == {"features"}


def test_touched_maps_a_diff_to_features(tmp_path):
    feats = load_features(_repo(tmp_path) / ".brief")
    hit = touched(feats, ["src/store/db.py", "README.md"])
    assert [f.feature_id for f in hit] == ["store"]


def test_check_clean_when_every_glob_matches(tmp_path):
    repo = _repo(tmp_path)
    assert check(repo, repo / ".brief") == []


def test_check_blocks_glob_left_dead_by_a_move(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "mv", "cli/search.py", "cli/find.py")
    v = check(repo, repo / ".brief")
    assert [(x.kind, x.anchor_id) for x in v] == [("empty-glob", "search")]
    assert "cli/search.py" in v[0].detail


def test_check_range_mode_reads_head_tree(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "branch", "base")
    _git(repo, "rm", "-rq", "src/store")
    _git(repo, "commit", "-qm", "drop store")
    v = check(repo, repo / ".brief", base="base")
    assert [(x.kind, x.anchor_id) for x in v] == [("empty-glob", "store")]


def test_feature_paths_do_not_arm_needs_conformance(tmp_path):
    # paths are a map, not related_code: an active feature map governs nothing
    repo = _repo(tmp_path, MAP.replace("type: features\n", "type: features\nstatus: active\n"))
    write(repo / "src" / "search" / "index.py", "x = 2\n")
    _git(repo, "add", "-A")
    assert check(repo, repo / ".brief") == []


def test_decision_gate_still_applies_alongside_map(tmp_path):
    repo = _repo(tmp_path)
    write(repo / ".brief" / "docs" / "adr-search.md", ACTIVE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "adr")
    write(repo / "src" / "search" / "index.py", "x = 2\n")
    _git(repo, "add", "-A")
    v = check(repo, repo / ".brief")
    assert [(x.kind, x.anchor_id) for x in v] == [("needs-conformance", "search-rule")]


def test_doctor_flags_feature_without_paths(tmp_path):
    no_paths = MAP.replace('```yaml\npaths: "src/store/**"\n```\n', "")
    repo = _repo(tmp_path, no_paths)
    kinds = [(f.kind, f.anchor) for f in doctor.run(repo, repo / ".brief").findings]
    assert ("feature-no-paths", "store") in kinds


def test_cli_features_filters_by_files(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)
    out = CliRunner().invoke(app, ["features", "cli/search.py", "--json"])
    assert out.exit_code == 0, out.output
    assert [f["feature_id"] for f in json.loads(out.output)] == ["search"]


def test_brief_dogfood_map_has_no_dead_globs():
    root = Path(__file__).resolve().parents[1]
    bd = root / ".brief"
    feats = load_features(bd)
    assert feats and all(f.paths for f in feats)
    from brief.features import empty_globs
    from brief.gitutil import tracked_files

    assert empty_globs(feats, tracked_files(root)) == []


def test_doctor_treats_a_referenced_map_as_descriptive(tmp_path):
    repo = _repo(tmp_path)
    write(repo / "src" / "search" / "index.py", f"# see {SEARCH_REF}\n")
    _git(repo, "add", "-A")
    assert doctor.run(repo, repo / ".brief").clean
