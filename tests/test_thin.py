import subprocess
from pathlib import Path

import pytest

from brief.docs import load_index
from brief.gate import check_staged, evaluate, glob_match
from brief.refs import DocRef, find_refs
from brief.resolve import ResolveError, resolve

DOC = """---
id: ADR-001-backend
project: acme
title: Sandbox backend
status: active
related_code:
  - "src/sandbox/**"
  - "src/docker.rs"
---

<!-- brief:anchor sandbox-backend-single-only -->
## single is the only backend

single is THE single sandbox backend. The Docker backend is deleted.

### Invariant
- No second Backend ships without a superseding decision.
"""

DRAFT_DOC = """---
id: ADR-002-draft
project: acme
title: A forming decision
status: draft
related_code:
  - "src/forming/**"
---

<!-- brief:anchor forming-thing -->
## Still forming
Not yet ratified.
"""


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make_brief(root: Path, draft: bool = False) -> Path:
    bd = root / ".brief"
    write(bd / "project.yaml", "id: acme\n")
    write(bd / "docs" / "ADR-001-backend.md", DOC)
    if draft:
        write(bd / "docs" / "ADR-002-draft.md", DRAFT_DOC)
    return bd


# --- refs ---

def test_ref_roundtrip():
    s = "doc://acme/ADR-001-backend@latest#sandbox-backend-single-only"
    r = DocRef.parse(s)
    assert (r.project, r.doc_id, r.rev, r.anchor) == (
        "acme", "ADR-001-backend", "latest", "sandbox-backend-single-only")
    assert str(r) == s and r.is_alias


@pytest.mark.parametrize("bad", ["acme/ROADMAP", "doc://acme/ROADMAP", "http://x/y@1"])
def test_ref_invalid(bad):
    with pytest.raises(ValueError):
        DocRef.parse(bad)


def test_find_refs():
    code = "// Context: doc://acme/ADR-001-backend@latest#sandbox-backend-single-only\nfoo();"
    refs = find_refs(code)
    assert len(refs) == 1 and refs[0].doc_id == "ADR-001-backend"


# --- resolve ---

def test_parse_and_resolve(tmp_path):
    bd = make_brief(tmp_path)
    res = resolve("doc://acme/ADR-001-backend@latest#sandbox-backend-single-only", bd)
    assert res.path.endswith("ADR-001-backend.md")
    assert res.title == "single is the only backend"
    assert res.start_line and res.end_line and res.end_line >= res.start_line
    assert res.hash.startswith("sha256:")


def test_resolve_unknown_anchor(tmp_path):
    bd = make_brief(tmp_path)
    with pytest.raises(ResolveError):
        resolve("doc://acme/ADR-001-backend@latest#nope", bd)


def test_resolve_concrete_rev_unsupported(tmp_path):
    bd = make_brief(tmp_path)
    with pytest.raises(ResolveError):
        resolve("doc://acme/ADR-001-backend@0001#sandbox-backend-single-only", bd)


# --- glob ---

def test_glob_match():
    assert glob_match("src/sandbox/**", "src/sandbox/single/mod.rs")
    assert glob_match("src/sandbox/**", "src/sandbox/mod.rs")
    assert glob_match("src/docker.rs", "src/docker.rs")
    assert glob_match("src/*.rs", "src/main.rs")
    assert not glob_match("src/sandbox/**", "src/vault/mod.rs")
    assert not glob_match("src/*.rs", "src/a/b.rs")


# --- gate (pure) — separation of powers ---

def test_governed_change_needs_conformance(tmp_path):
    index = load_index(make_brief(tmp_path))
    v = evaluate(["src/sandbox/single/mod.rs"], set(), index, set(), set())
    assert len(v) == 1 and v[0].kind == "needs-conformance"
    assert v[0].anchor_id == "sandbox-backend-single-only"


def test_conforms_passes(tmp_path):
    index = load_index(make_brief(tmp_path))
    v = evaluate(["src/sandbox/single/mod.rs"], set(), index,
                 {"sandbox-backend-single-only"}, set())
    assert v == []


def test_amend_proposed_blocks_as_escalation(tmp_path):
    index = load_index(make_brief(tmp_path))
    v = evaluate(["src/sandbox/single/mod.rs"], set(), index,
                 set(), {"sandbox-backend-single-only"})
    assert len(v) == 1 and v[0].kind == "amendment-required"


def test_editing_ratified_decision_is_blocked(tmp_path):
    index = load_index(make_brief(tmp_path))
    # ADR-001-backend was modified and is locked at HEAD -> ratified-edit
    v = evaluate(["src/sandbox/x.rs"], {"ADR-001-backend"}, index, set(), set())
    assert any(x.kind == "ratified-edit" and x.doc_id == "ADR-001-backend" for x in v)
    # and it does NOT also demand conformance for the same decision
    assert not any(x.kind == "needs-conformance" and x.doc_id == "ADR-001-backend" for x in v)


def test_ungoverned_passes(tmp_path):
    index = load_index(make_brief(tmp_path))
    assert evaluate(["src/vault/mod.rs", "README.md"], set(), index, set(), set()) == []


def test_draft_decision_not_gated(tmp_path):
    index = load_index(make_brief(tmp_path, draft=True))
    # changing code governed by a DRAFT decision needs no conformance
    assert evaluate(["src/forming/x.rs"], set(), index, set(), set()) == []


# --- gate (git integration) ---

def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)


def _init(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")


def test_check_staged_blocks_ratified_edit(tmp_path):
    repo = tmp_path
    _init(repo)
    make_brief(repo)
    write(repo / "src" / "sandbox" / "single" / "mod.rs", "// initial\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    # agent edits the ratified decision to ratify its own change -> blocked
    doc = repo / ".brief" / "docs" / "ADR-001-backend.md"
    doc.write_text(doc.read_text().replace("status: active", "status: superseded"))
    (repo / "src" / "sandbox" / "single" / "mod.rs").write_text("// changed\n")
    _git(repo, "add", "-A")
    v = check_staged(repo, repo / ".brief")
    assert any(x.kind == "ratified-edit" for x in v)


def test_check_staged_conforms_passes(tmp_path):
    repo = tmp_path
    _init(repo)
    make_brief(repo)
    write(repo / "src" / "sandbox" / "single" / "mod.rs", "// initial\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    # governed change + truthful conforms sign-off -> passes
    (repo / "src" / "sandbox" / "single" / "mod.rs").write_text("// refactor only\n")
    write(repo / ".brief" / "SIGNOFF", "sandbox-backend-single-only conforms: pure refactor\n")
    _git(repo, "add", "-A")
    assert check_staged(repo, repo / ".brief") == []


def test_check_staged_broken_ref(tmp_path):
    repo = tmp_path
    _init(repo)
    make_brief(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    write(repo / "src" / "other.rs", "// Context: doc://acme/ADR-001-backend@latest#ghost\n")
    # also sign conforms so the only finding is the broken ref
    write(repo / ".brief" / "SIGNOFF", "sandbox-backend-single-only conforms: n/a\n")
    _git(repo, "add", "-A")
    v = check_staged(repo, repo / ".brief")
    assert any(x.kind == "broken-ref" for x in v)


# --- init ---

def test_init_scaffolds(tmp_path):
    from brief.init import init_vault

    _init(tmp_path)
    init_vault(tmp_path)
    assert (tmp_path / ".brief" / "docs").is_dir()
    assert (tmp_path / ".brief" / "amendments").is_dir()
    assert (tmp_path / ".brief" / "project.yaml").exists()
    agents = tmp_path / "AGENTS.md"
    assert agents.exists() and "## Context Vault (brief)" in agents.read_text()
    # hook-free by default (non-viral); enforcement is CI / agent-run check
    assert not (tmp_path / ".git" / "hooks" / "pre-commit").exists()
    # idempotent: re-running does not duplicate the convention
    init_vault(tmp_path)
    assert agents.read_text().count("## Context Vault (brief)") == 1


def test_init_optin_hook_and_ci(tmp_path):
    from brief.init import init_vault

    _init(tmp_path)
    init_vault(tmp_path, ci=True, hook=True)
    assert (tmp_path / ".git" / "hooks" / "pre-commit").exists()
    assert (tmp_path / ".github" / "workflows" / "brief.yml").exists()


# --- versioning / revisions ---

def test_publish_and_resolve_revision(tmp_path):
    from brief import versions

    bd = make_brief(tmp_path)
    rev = versions.publish(bd, "ADR-001-backend")
    assert rev == 1 and versions.version_path(bd, "ADR-001-backend", 1).exists()
    # @0001 → frozen file; @latest → alias to it; @current → live doc
    r1 = resolve("doc://acme/ADR-001-backend@0001#sandbox-backend-single-only", bd)
    assert r1.rev == "0001" and "v0001.md" in r1.path
    r2 = resolve("doc://acme/ADR-001-backend@latest#sandbox-backend-single-only", bd)
    assert r2.rev == "0001"
    r3 = resolve("doc://acme/ADR-001-backend@current#sandbox-backend-single-only", bd)
    assert r3.rev == "current" and r3.path.endswith("ADR-001-backend.md")


def test_stale_detection(tmp_path):
    from brief import versions

    bd = make_brief(tmp_path)
    versions.publish(bd, "ADR-001-backend")  # v1
    live = versions.live_doc(bd, "ADR-001-backend")
    live.write_text(live.read_text().replace("The Docker backend is deleted.", "Docker backend removed."))
    versions.publish(bd, "ADR-001-backend")  # v2
    stale = resolve("doc://acme/ADR-001-backend@0001#sandbox-backend-single-only", bd)
    assert stale.stale is True and stale.stale_since == "0002"
    fresh = resolve("doc://acme/ADR-001-backend@0002#sandbox-backend-single-only", bd)
    assert fresh.stale is False


# --- pin ---

def test_pin_rewrites_latest(tmp_path):
    from brief import versions
    from brief.pin import pin_text

    bd = make_brief(tmp_path)
    versions.publish(bd, "ADR-001-backend")  # latest = 1
    text = "// Context: doc://acme/ADR-001-backend@latest#sandbox-backend-single-only\n"
    new, changes = pin_text(text, bd)
    assert "@0001#" in new and "@latest" not in new
    assert len(changes) == 1 and changes[0].new


def test_pin_leaves_unpublished_stable_and_pinned(tmp_path):
    from brief.pin import pin_text

    bd = make_brief(tmp_path)  # not published
    text = (
        "a doc://acme/ADR-001-backend@latest#x\n"
        "b doc://acme/ADR-001-backend@stable#x\n"
        "c doc://acme/ADR-001-backend@0003#x\n"
    )
    new, changes = pin_text(text, bd)
    assert new == text  # @latest unpublished → left; @stable and @0003 untouched
    assert any(c.new is None for c in changes)


def test_pin_files(tmp_path):
    from brief import versions
    from brief.pin import pin_files

    bd = make_brief(tmp_path)
    versions.publish(bd, "ADR-001-backend")
    f = tmp_path / "src" / "x.rs"
    f.parent.mkdir(parents=True)
    f.write_text("// doc://acme/ADR-001-backend@latest#sandbox-backend-single-only\n")
    pin_files([f], bd)
    assert "@0001#" in f.read_text()


# --- ratify ---

def test_ratify_flow(tmp_path):
    from brief import versions
    from brief.ratify import ratify

    bd = make_brief(tmp_path)
    versions.publish(bd, "ADR-001-backend")  # v1
    (bd / "amendments").mkdir(exist_ok=True)
    (bd / "amendments" / "sandbox-backend-single-only.md").write_text("# proposal\nadmit qemu\n")
    live = versions.live_doc(bd, "ADR-001-backend")
    live.write_text(live.read_text() + "\n- qemu admitted experimentally.\n")  # human edits the decision

    r = ratify(bd, "sandbox-backend-single-only", by="vu")
    assert r.rev == 2 and versions.version_path(bd, "ADR-001-backend", 2).exists()
    assert not (bd / "amendments" / "sandbox-backend-single-only.md").exists()
    assert (bd / "amendments" / "archive" / "sandbox-backend-single-only-v0002.md").exists()


def test_gate_allows_ratification(tmp_path):
    from brief import versions
    from brief.gate import check

    repo = tmp_path
    _init(repo)
    make_brief(repo)
    bd = repo / ".brief"
    versions.publish(bd, "ADR-001-backend")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init+publish")

    # a ratification: the locked decision is edited, with the archived amendment present
    live = versions.live_doc(bd, "ADR-001-backend")
    live.write_text(live.read_text() + "\n- amended.\n")
    (bd / "amendments" / "archive").mkdir(parents=True, exist_ok=True)
    (bd / "amendments" / "archive" / "sandbox-backend-single-only-v0002.md").write_text("ratified\n")
    _git(repo, "add", "-A")
    v = check(repo, bd)
    assert not any(x.kind == "ratified-edit" for x in v)


def test_check_range_mode(tmp_path):
    repo = tmp_path
    _init(repo)
    make_brief(repo)
    write(repo / "src" / "sandbox" / "x.rs", "// base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    # branch commit: governed code changed without conforms — range mode sees committed changes
    (repo / "src" / "sandbox" / "x.rs").write_text("// changed on branch\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "feature")
    from brief.gate import check

    v = check(repo, repo / ".brief", base=base)
    assert any(x.kind == "needs-conformance" for x in v)
