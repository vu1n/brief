import subprocess
from pathlib import Path

from brief import doctor, versions

# --- fixtures ---

ACTIVE = """---
id: adr-backend
project: acme
status: active
related_code:
  - "src/sandbox/**"
---

<!-- brief:anchor one-backend -->
## one backend
### Invariant
- one only.
"""

DRAFT = """---
id: forming
project: acme
status: draft
related_code:
  - "src/forming/**"
---

<!-- brief:anchor forming-thing -->
## still forming
Not yet ratified.
"""


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)


def _init(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _bd(repo: Path) -> Path:
    write(repo / ".brief" / "project.yaml", "id: acme\n")
    return repo / ".brief"


def _kinds(report) -> set[str]:
    return {f.kind for f in report.findings}


# --- active-unpublished + active-unwired: an active decision, never published, no back-ref ---


def test_active_unpublished_and_unwired(tmp_path):
    repo = tmp_path
    _init(repo)
    bd = _bd(repo)
    write(bd / "docs" / "adr-backend.md", ACTIVE)  # active, NOT published
    write(repo / "src" / "sandbox" / "mod.rs", "// no ref here\nfn f() {}\n")
    _git(repo, "add", "-A")

    r = doctor.run(repo, bd)
    kinds = _kinds(r)
    assert "active-unpublished" in kinds  # @latest floats to a mutable doc
    assert "active-unwired" in kinds       # governed file carries no back-ref
    # the fix strings are actionable, not prose
    unwired = next(f for f in r.findings if f.kind == "active-unwired")
    assert "Context: doc://acme/adr-backend@latest#one-backend" in unwired.fix
    assert unwired.file == "src/sandbox/mod.rs"


# --- clean: published, wired with a pinned ref, not stale ---


def test_published_and_wired_is_clean(tmp_path):
    repo = tmp_path
    _init(repo)
    bd = _bd(repo)
    write(bd / "docs" / "adr-backend.md", ACTIVE)
    versions.publish(bd, "adr-backend")  # -> v0001, latest=1
    write(
        repo / "src" / "sandbox" / "mod.rs",
        "// Context: doc://acme/adr-backend@0001#one-backend\nfn f() {}\n",
    )
    _git(repo, "add", "-A")

    r = doctor.run(repo, bd)
    assert r.clean, [f.to_dict() for f in r.findings]


# --- unpinned-ref: published doc, code still floats on @latest ---


def test_unpinned_ref(tmp_path):
    repo = tmp_path
    _init(repo)
    bd = _bd(repo)
    write(bd / "docs" / "adr-backend.md", ACTIVE)
    versions.publish(bd, "adr-backend")
    write(
        repo / "src" / "sandbox" / "mod.rs",
        "// Context: doc://acme/adr-backend@latest#one-backend\nfn f() {}\n",
    )
    _git(repo, "add", "-A")

    r = doctor.run(repo, bd)
    kinds = _kinds(r)
    assert "unpinned-ref" in kinds
    assert "active-unwired" not in kinds  # it IS referenced, just not pinned
    assert "active-unpublished" not in kinds  # it IS published


# --- draft-governing-code (info): code leans on an unpublished draft ---


def test_draft_governing_code_is_info(tmp_path):
    repo = tmp_path
    _init(repo)
    bd = _bd(repo)
    write(bd / "docs" / "forming.md", DRAFT)  # draft, unpublished
    write(
        repo / "src" / "forming" / "x.rs",
        "// Context: doc://acme/forming@latest#forming-thing\nfn f() {}\n",
    )
    _git(repo, "add", "-A")

    r = doctor.run(repo, bd)
    dg = next((f for f in r.findings if f.kind == "draft-governing-code"), None)
    assert dg is not None and dg.severity == "info"
    assert "active-unpublished" not in _kinds(r)  # draft is not locked → not this check
    assert dg not in r.warnings  # info doesn't count toward --strict


# --- stale-ref: pinned to v1, the anchor moved in v2 ---


def test_stale_ref(tmp_path):
    repo = tmp_path
    _init(repo)
    bd = _bd(repo)
    write(bd / "docs" / "adr-backend.md", ACTIVE)
    versions.publish(bd, "adr-backend")  # v0001
    # edit the anchor body, publish again -> v0002 with a different hash
    write(bd / "docs" / "adr-backend.md", ACTIVE.replace("one only.", "one only, forever."))
    versions.publish(bd, "adr-backend")  # v0002, latest=2
    write(
        repo / "src" / "sandbox" / "mod.rs",
        "// Context: doc://acme/adr-backend@0001#one-backend\nfn f() {}\n",
    )
    _git(repo, "add", "-A")

    r = doctor.run(repo, bd)
    stale = next((f for f in r.findings if f.kind == "stale-ref"), None)
    assert stale is not None and stale.severity == "warn"
    assert stale.file == "src/sandbox/mod.rs"


# --- output contract: to_dict is machine-first, render_md is the human view ---


def test_report_output_contract(tmp_path):
    repo = tmp_path
    _init(repo)
    bd = _bd(repo)
    write(bd / "docs" / "adr-backend.md", ACTIVE)
    write(repo / "src" / "sandbox" / "mod.rs", "fn f() {}\n")
    _git(repo, "add", "-A")

    r = doctor.run(repo, bd)
    d = r.to_dict()
    assert d["clean"] is False
    assert {"kind", "severity", "detail", "fix"} <= set(d["findings"][0])
    md = doctor.render_md(r)
    assert "brief doctor" in md and "fix:" in md
    # clean repo renders the clean banner
    assert "clean" in doctor.render_md(doctor.Report(repo="x", findings=[])).lower()
