"""Opt-in sign-off (`signoff: required`) and Context-scoped needs-conformance."""
import subprocess
from pathlib import Path

from brief.gate import check_staged, ref_blocks

REF_A = "doc:" + "//acme/retry@latest#idempotent-only"
REF_B = "doc:" + "//acme/retry@latest#backoff"

DOC = """---
id: retry
status: active
{signoff}related_code:
  - "src/**"
---
<!-- brief:anchor idempotent-only -->
## Retry idempotent calls only

<!-- brief:anchor backoff -->
## Exponential backoff
"""

CODE = f"""import time


# Context: {REF_A} — retry only idempotent calls
def should_retry(method):
    allowed = {{"GET", "PUT"}}
    return method in allowed


# Context: {REF_B} — exponential backoff
def delay(attempt):
    return 2 ** attempt


def unrelated():
    return 1
"""


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)


def _repo(tmp_path: Path, signoff: bool = True, code: str = CODE) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".brief" / "docs").mkdir(parents=True)
    (tmp_path / ".brief" / "project.yaml").write_text("id: acme\n")
    (tmp_path / ".brief" / "docs" / "retry.md").write_text(
        DOC.format(signoff="signoff: required\n" if signoff else "")
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "retry.py").write_text(code)
    (tmp_path / "src" / "unwired.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _edit(repo: Path, rel: str, old: str, new: str) -> list:
    p = repo / rel
    text = p.read_text()
    assert old in text
    p.write_text(text.replace(old, new))
    _git(repo, "add", "-A")
    return check_staged(repo, repo / ".brief")


def _needs(v) -> set[str]:
    return {x.anchor_id for x in v if x.kind == "needs-conformance"}


def test_no_signoff_means_no_conformance_ask(tmp_path):
    repo = _repo(tmp_path, signoff=False)
    assert _edit(repo, "src/retry.py", '"GET", "PUT"', '"GET", "PUT", "POST"') == []


def test_no_signoff_decision_is_still_read_only(tmp_path):
    repo = _repo(tmp_path, signoff=False)
    v = _edit(repo, ".brief/docs/retry.md", "idempotent calls only", "every call")
    assert any(x.kind == "ratified-edit" for x in v)


def test_no_signoff_decision_still_blocks_on_amend_proposed(tmp_path):
    repo = _repo(tmp_path, signoff=False)
    (repo / ".brief" / "SIGNOFF").write_text("idempotent-only amend-proposed: POST must retry\n")
    v = _edit(repo, "src/retry.py", '"GET", "PUT"', '"GET", "PUT", "POST"')
    assert {x.anchor_id for x in v if x.kind == "amendment-required"} == {"idempotent-only"}


def test_edit_outside_any_context_block_needs_no_signoff(tmp_path):
    repo = _repo(tmp_path)
    assert _needs(_edit(repo, "src/retry.py", "return 1", "return 2")) == set()


def test_edit_inside_a_block_needs_only_that_anchor(tmp_path):
    repo = _repo(tmp_path)
    assert _needs(_edit(repo, "src/retry.py", '"GET", "PUT"', '"GET", "PUT", "POST"')) == {"idempotent-only"}


def test_removing_a_context_ref_needs_its_anchor(tmp_path):
    repo = _repo(tmp_path)
    v = _edit(repo, "src/retry.py", f"# Context: {REF_A} — retry only idempotent calls\n", "")
    assert _needs(v) == {"idempotent-only"}


def test_unwired_governed_file_needs_every_anchor(tmp_path):
    repo = _repo(tmp_path)
    assert _needs(_edit(repo, "src/unwired.py", "x = 1", "x = 2")) == {"idempotent-only", "backoff"}


def test_ref_blocks_python_brace_and_trailing():
    py = ref_blocks(CODE, "retry")
    assert [(a, s, e) for s, e, a in py] == [("idempotent-only", 4, 7), ("backoff", 10, 12)]
    rust = f"// Context: {REF_A} — x\nfn f() {{\n    a();\n}}\n\nfn g() {{}}\n"
    assert ref_blocks(rust, "retry") == [(1, 4, "idempotent-only")]
    trailing = f"x = 1\nLIMIT = 3  # Context: {REF_B} — y\ny = 2\n"
    assert ref_blocks(trailing, "retry") == [(2, 2, "backoff")]
    assert ref_blocks(CODE, "other-doc") == []


def test_comment_only_edit_needs_no_signoff(tmp_path):
    repo = _repo(tmp_path)
    v = _edit(repo, "src/retry.py", "— retry only idempotent calls", "— only idempotent methods retry")
    assert _needs(v) == set()


def test_replacing_a_ref_with_a_why_comment_asks_only_signoff_decisions(tmp_path):
    # kypp#2: demoting decisions to why-comments touched only comments
    new = "# Why: POST is not idempotent, so it never retries.\n"
    assert _needs(_edit(_repo(tmp_path / "a", signoff=False), "src/retry.py",
                        f"# Context: {REF_A} — retry only idempotent calls\n", new)) == set()
    assert _needs(_edit(_repo(tmp_path / "b"), "src/retry.py",
                        f"# Context: {REF_A} — retry only idempotent calls\n", new)) == {"idempotent-only"}


def test_code_hiding_behind_a_trailing_ref_is_not_comment_only(tmp_path):
    repo = _repo(tmp_path)
    v = _edit(repo, "src/retry.py", "    return 2 ** attempt",
              f"    return 3 ** attempt  # Context: {REF_B} — exponential backoff")
    assert _needs(v) == {"backoff"}


def test_hash_code_lines_are_not_comments():
    from brief.gate import _is_comment

    assert _is_comment("  # why") and _is_comment("// why") and _is_comment("")
    assert not _is_comment("#[derive(Debug)]") and not _is_comment("#include <x.h>")
    assert not _is_comment("x = 1  # trailing")
