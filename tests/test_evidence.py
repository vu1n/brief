"""`brief evidence`: an advisory view of each pending amendment. Exact source lines, scope
deltas, linked decisions; an optional model only adds labeled, inferred links. It writes
nothing and nothing that decides (gate, triage, ratify, threads) reads it."""
import ast
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS

from brief import versions
from brief.evidence import evidence, render_md, to_dict
from brief.gate import check
from brief.triage import triage_amendments, verdict

from tests.test_amend_merge import ANCHOR, _head
from tests.test_thin import _git, _published_repo, write

AMENDMENT = """# Amendment proposal: sandbox-backend-single-only

## What should change
Allow a second backend behind a flag.

## Why
A customer needs docker. Tests pass on the branch.
"""

CACHE = """---
id: cache-staleness
project: acme
title: Bounded staleness
status: active
related_code:
  - "src/cache/**"
---

<!-- brief:anchor bounded-staleness -->
## Reads are stale for at most 5 seconds
Relies on doc://acme/ADR-001-backend@latest#sandbox-backend-single-only for one writer.
"""

UNRELATED = """---
id: exit-codes
project: acme
title: Exit codes
status: active
related_code:
  - "src/errors.rs"
---

<!-- brief:anchor exit-codes -->
## Exit codes never renumber
"""

SHARED = """---
id: mod-layout
project: acme
title: Module layout
status: active
related_code:
  - "src/sandbox/mod.rs"
---

<!-- brief:anchor mod-layout -->
## One module per backend
"""


def _pr(tmp_path, narrow=False, others=True):
    repo, bd = _published_repo(tmp_path)
    if others:
        write(bd / "docs" / "cache-staleness.md", CACHE)
        write(bd / "docs" / "exit-codes.md", UNRELATED)
        write(bd / "docs" / "mod-layout.md", SHARED)
        write(repo / "src" / "docker.rs", "// Context: doc://acme/ADR-001-backend@latest#sandbox-backend-single-only\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "more decisions")
    base = _head(repo)
    live = versions.live_doc(bd, "ADR-001-backend")
    text = live.read_text().replace("- No second Backend ships without a superseding decision.",
                                    "- A second Backend may ship behind a flag.")
    if narrow:
        text = text.replace('  - "src/docker.rs"\n', "")
        write(repo / "src" / "docker.rs", "// docker is back\n")
    live.write_text(text)
    write(bd / "amendments" / f"{ANCHOR}.md", AMENDMENT)
    write(bd / "SIGNOFF", f"{ANCHOR} amend-proposed: second backend\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "amend")
    return repo, bd, base


class Fake:
    def __init__(self, by_doc=None, fail=False):
        self.by_doc, self.fail, self.calls = by_doc or {}, fail, []

    def system_one(self, state, questions):
        self.calls.append(state)
        if self.fail:
            raise OSError("down")
        p = next((p for k, p in self.by_doc.items() if k in state["other_decision"]), 0.01)
        return NS(model="clef", answers={"undermines": NS(type="noul", noul=p)})


def test_changed_lines_and_qualifiers_are_exact(tmp_path):
    repo, bd, base = _pr(tmp_path, others=False)
    [e] = evidence(repo, bd, base, model=False)
    assert (e.doc_id, e.anchor_id) == ("ADR-001-backend", ANCHOR)
    lines = (bd / "docs" / "ADR-001-backend.md").read_text().splitlines()
    [rm], [add] = e.removed, e.added
    assert rm.text == "- No second Backend ships without a superseding decision."
    assert lines[add.line - 1] == add.text == "- A second Backend may ship behind a flag."
    assert rm.line == add.line  # same place in the file at the baseline
    assert e.qualifiers_removed == ["without"] and e.qualifiers_added == ["may"]


def test_amendment_sections_gaps_and_unverified_claims(tmp_path):
    repo, bd, base = _pr(tmp_path, others=False)
    [e] = evidence(repo, bd, base, model=False)
    assert e.sections["What should change"].text == "Allow a second backend behind a flag."
    assert e.sections["Why"].line == 7
    assert any("Code that needs it" in g and "Impact / risk" in g for g in e.gaps)
    assert [c.line for c in e.claims] == [7]  # "Tests pass" is the author's claim, not a result
    assert "Unverified claim" in render_md([e])


def test_narrowed_scope_shows_files_leaving_governance(tmp_path):
    repo, bd, base = _pr(tmp_path, narrow=True)
    [e] = evidence(repo, bd, base, model=False)
    assert '"src/docker.rs"' not in str(e.scope_after) and "src/docker.rs" in e.scope_before
    assert e.leaving == e.leaving_changed == ["src/docker.rs"]
    assert "leaving governance" in render_md([e])


def test_explicit_and_shared_file_links_and_code_sites(tmp_path):
    repo, bd, base = _pr(tmp_path)
    [e] = evidence(repo, bd, base, model=False)
    links = {ln.doc_id: ln for ln in e.links}
    assert links["cache-staleness"].how == ["cites-it"]
    assert links["mod-layout"].how == ["shared-files"] and links["mod-layout"].files == ["src/sandbox/mod.rs"]
    assert "exit-codes" not in links
    assert e.code_refs == ["src/docker.rs:1"]
    assert e.model == "not run (--no-model)"


def test_model_adds_only_labeled_links_above_the_bar(tmp_path):
    repo, bd, base = _pr(tmp_path)
    fake = Fake({"Exit codes": 0.8, "One module per backend": 0.3})
    [e] = evidence(repo, bd, base, via=fake)
    links = {ln.doc_id: ln for ln in e.links}
    assert links["exit-codes"].how == ["model"] and links["exit-codes"].p == 0.8
    assert links["mod-layout"].how == ["shared-files"] and links["mod-layout"].p == 0.3
    assert len(fake.calls) == 3  # every other decision, never the amended one
    assert e.model == "clef"  # who answered, not the configured alias
    assert "inferred by the model only" in render_md([e])


def test_model_failure_is_not_checked_never_no_impact(tmp_path):
    repo, bd, base = _pr(tmp_path)
    [e] = evidence(repo, bd, base, via=Fake(fail=True))
    assert any("not checked, not cleared" in g for g in e.gaps)
    assert all(ln.p is None for ln in e.links) and not any("model" in ln.how for ln in e.links)


def test_no_model_configured_says_inferred_impacts_were_not_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIEF_S1", "off")
    repo, bd, base = _pr(tmp_path)
    [e] = evidence(repo, bd, base)
    assert e.model.startswith("not run") and "not checked" in e.model


def test_evidence_changes_no_decision_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIEF_S1", "off")  # triage below: no live model
    repo, bd, base = _pr(tmp_path, narrow=True)
    gate_before = [(v.kind, v.anchor_id, v.blocking) for v in check(repo, bd, base)]
    rated = verdict(triage_amendments(repo, bd, base, via=None))
    evidence(repo, bd, base, via=Fake({"Exit codes": 0.99}))
    assert [(v.kind, v.anchor_id, v.blocking) for v in check(repo, bd, base)] == gate_before
    assert verdict(triage_amendments(repo, bd, base, via=None)) == rated
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                            capture_output=True, text=True, check=True).stdout
    assert status == ""


def test_nothing_that_decides_imports_evidence():
    import brief

    root = Path(brief.__file__).parent
    for mod in ("gate", "triage", "ratify", "threads", "verdicts"):
        tree = ast.parse((root / f"{mod}.py").read_text())
        names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not any("evidence" in n for n in names), mod


def test_no_pending_amendment_is_empty(tmp_path):
    repo, bd = _published_repo(tmp_path)
    assert evidence(repo, bd, _head(repo), model=False) == []
    assert to_dict([]) == {"advisory": True, "amendments": []}


def test_frontmatter_only_edit_shows_each_changed_field(tmp_path):
    repo, bd = _published_repo(tmp_path)
    base = _head(repo)
    live = versions.live_doc(bd, "ADR-001-backend")
    live.write_text(live.read_text().replace("status: active", "status: superseded").replace("signoff: required\n", ""))
    write(bd / "amendments" / f"{ANCHOR}.md", AMENDMENT)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "demote")
    [e] = evidence(repo, bd, base, model=False)
    assert e.frontmatter == ["signoff: 'required' -> None", "status: 'active' -> 'superseded'"]
    assert any("frontmatter only" in g for g in e.gaps)
    assert "status: 'active' -> 'superseded'" in render_md([e])


def test_file_renamed_out_of_scope_counts_as_leaving(tmp_path):
    repo, bd = _published_repo(tmp_path)
    write(repo / "src" / "sandbox" / "pool.rs", "// pool\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "pool")
    base = _head(repo)
    _git(repo, "mv", "src/sandbox/pool.rs", "src/pool.rs")
    live = versions.live_doc(bd, "ADR-001-backend")
    live.write_text(live.read_text().replace("is deleted", "is gone"))
    write(bd / "amendments" / f"{ANCHOR}.md", AMENDMENT)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "move")
    [e] = evidence(repo, bd, base, model=False)
    assert e.leaving == e.leaving_changed == ["src/sandbox/pool.rs"]
