import subprocess
from pathlib import Path

from brief import scan


def _w(p: Path, t: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(t, encoding="utf-8")


def test_build_map(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    _w(tmp_path / "docs/decisions/adr-001-backend.md", "---\nstatus: accepted\n---\n# One backend\nThe rule holds.\n")
    _w(tmp_path / "docs/decisions/adr-002-untracked.md", "# Untracked decision\nno status field here\n")
    _w(tmp_path / "docs/plans/plan.md", "# Plan\n- [ ] do a thing\n")
    _w(tmp_path / "docs/design/state.md", "# State model\nDRAFT\n")
    _w(tmp_path / "README.md", "# proj\n")
    _w(
        tmp_path / "src/foo.rs",
        "// Context: doc://proj/adr-001-backend@latest#one-backend\n"
        "fn f() {}\n"
        "// Decision: use X because it is simpler\n"
        "let y = 1;\n",
    )
    # track everything except the untracked ADR
    subprocess.run(
        ["git", "-C", str(tmp_path), "add",
         "docs/decisions/adr-001-backend.md", "docs/plans/plan.md",
         "docs/design/state.md", "src/foo.rs", "README.md"],
        check=True, capture_output=True,
    )

    m = scan.build_map(tmp_path)
    by = {d.path: d for d in m.docs}

    # classification + status + tracked
    adr = by["docs/decisions/adr-001-backend.md"]
    assert adr.genre == "adr" and adr.has_status and adr.tracked
    assert by["docs/decisions/adr-002-untracked.md"].genre == "adr"
    assert not by["docs/decisions/adr-002-untracked.md"].tracked
    assert by["docs/plans/plan.md"].genre == "plan"
    assert by["docs/design/state.md"].genre == "design"
    assert by["README.md"].genre == "readme"

    # decision-genre grouping + untracked / status-less surfacing
    assert {d.genre for d in m.decision_docs} == {"adr", "design"}
    assert any(d.path.endswith("adr-002-untracked.md") for d in m.untracked_decisions)
    assert any(d.path.endswith("adr-002-untracked.md") for d in m.status_less_decisions)

    # code signals: a ref and a context/rationale comment
    kinds = {s.kind for s in m.signals}
    assert "ref" in kinds and "context" in kinds

    # module tree includes src
    assert any("src" in mod for mod in m.modules)

    # render is stable and highlights the risks
    md = scan.render_map_md(m)
    assert "untracked" in md.lower() and "adr-001-backend" in md


def test_scan_skips_noise_dirs(tmp_path):
    _w(tmp_path / "node_modules/pkg/x.js", "// Decision: should be ignored\n")
    _w(tmp_path / "src/keep.ts", "// Context: doc://p/d@latest#a\n")
    m = scan.build_map(tmp_path)
    files = {s.file for s in m.signals}
    assert "src/keep.ts" in files
    assert not any("node_modules" in f for f in files)
    assert not any("node_modules" in mod for mod in m.modules)
