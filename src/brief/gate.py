"""L0 governance gate — separation of powers.

A ratified decision is a CONSTRAINT the coding loop is checked against, not state
the coding loop may rewrite. So the gate enforces:

1. ratified-edit   — a coding commit must NOT modify a locked (active/ratified)
                     decision. To change one, propose an amendment for human
                     ratification. (This is the fix for "reversal by fiat": the
                     constrained party cannot edit the constraint to pass.)
2. needs-conformance — when governed code changes, the author must record either
                     `<anchor> conforms: <why>` (code still satisfies the decision)
                     or `<anchor> amend-proposed: <why>` in .brief/SIGNOFF.
3. amendment-required — `amend-proposed` blocks the commit: code that needs a
                     ratified decision changed cannot land until the amendment is
                     ratified. (A correct *escalation*, not a rule violation.)
4. broken-ref      — a doc:// ref added to code that does not resolve.

Whether code *conforms* to a standing decision is semantic (L1 sampling / L2 tests);
the gate does not attempt it. But because the decision is read-only, a "conforms"
claim is now falsifiable against a fixed target instead of one the author can edit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import docs, gitutil
from .docs import Decision, load_index
from .refs import find_refs
from .resolve import resolve

LOCKED_STATUSES = {"active", "ratified"}

CONFORMS_RE = re.compile(r"^\s*([a-z0-9][a-z0-9-]*)\s+conforms\b")
AMEND_RE = re.compile(r"^\s*([a-z0-9][a-z0-9-]*)\s+amend-proposed\b")


def glob_match(pattern: str, path: str) -> bool:
    """Match a path against a glob: ** spans directories, * stays within a segment."""
    rx: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            rx.append(".*")
            i += 2
            if i < len(pattern) and pattern[i] == "/":
                i += 1
        elif pattern[i] == "*":
            rx.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            rx.append("[^/]")
            i += 1
        else:
            rx.append(re.escape(pattern[i]))
            i += 1
    return re.match("^" + "".join(rx) + "$", path) is not None


def _is_brief_path(p: str) -> bool:
    return p.startswith(".brief/") or "/.brief/" in f"/{p}"


def _is_locked(status: str | None) -> bool:
    return (status or "").lower() in LOCKED_STATUSES


@dataclass
class Violation:
    kind: str  # ratified-edit | needs-conformance | amendment-required | broken-ref
    doc_id: str = ""
    anchor_id: str = ""
    files: list[str] = field(default_factory=list)
    detail: str = ""


def evaluate(
    changed_files: list[str],
    locked_edits: set[str],
    index: list[Decision],
    conforms: set[str],
    amend_proposed: set[str],
    bad_refs: list[tuple[str, str]] | None = None,
) -> list[Violation]:
    """Pure core. `locked_edits` = doc_ids of locked decisions modified in this commit."""
    code_changes = [f for f in changed_files if not _is_brief_path(f)]
    violations: list[Violation] = []

    for doc_id in sorted(locked_edits):
        violations.append(
            Violation(
                kind="ratified-edit",
                doc_id=doc_id,
                detail="ratified decision is read-only — propose an amendment, do not edit it to pass",
            )
        )

    for d in index:
        if not _is_locked(d.meta.get("status")):
            continue  # only locked decisions gate code; drafts are still forming
        if d.doc_id in locked_edits:
            continue  # already reported as ratified-edit
        governed = [f for f in code_changes if any(glob_match(g, f) for g in d.related_code)]
        if not governed:
            continue
        for a in d.anchors:
            if a.anchor_id in conforms:
                continue
            if a.anchor_id in amend_proposed:
                violations.append(
                    Violation(
                        kind="amendment-required",
                        doc_id=d.doc_id,
                        anchor_id=a.anchor_id,
                        files=governed,
                        detail="decision change proposed — needs human ratification before code can land",
                    )
                )
            else:
                violations.append(
                    Violation(
                        kind="needs-conformance",
                        doc_id=d.doc_id,
                        anchor_id=a.anchor_id,
                        files=governed,
                        detail="governed code changed — assert conforms or amend-proposed in .brief/SIGNOFF",
                    )
                )

    for ref, why in bad_refs or []:
        violations.append(Violation(kind="broken-ref", detail=f"{ref}: {why}"))
    return violations


def _relpath(p: Path, repo: Path) -> str:
    try:
        return str(p.resolve().relative_to(repo))
    except ValueError:
        return str(p)


def check(repo: Path, brief_dir: Path, base: str | None = None) -> list[Violation]:
    """Evaluate the gate over staged changes (base=None, local) or base..HEAD (CI)."""
    repo = repo.resolve()
    baseline_ref = gitutil.merge_base(repo, base) if base else "HEAD"
    rng = baseline_ref if base else None
    changed = gitutil.changed_files(repo, rng)
    changed_set = set(changed)
    index = load_index(brief_dir)

    # locked decisions modified in the range (status read at the baseline, so flipping
    # status in the same change can't dodge the check)
    locked_edits: set[str] = set()
    for d in index:
        rel = _relpath(d.path, repo)
        if rel in changed_set:
            head = gitutil.content_at(repo, rel, baseline_ref)
            if head and _is_locked(docs.status_of(head)):
                locked_edits.add(d.doc_id)

    # Ratification exemption: a locked decision edited alongside an archived amendment
    # for one of its anchors is an authorized ratification (L3), not a coding-loop reversal.
    for f in changed:
        name = f.rsplit("/", 1)[-1]
        if "/amendments/archive/" in f"/{f}" and name.endswith(".md"):
            anchor = re.sub(r"-v\d+\.md$", "", name)
            for d in index:
                if d.anchor(anchor):
                    locked_edits.discard(d.doc_id)

    conforms: set[str] = set()
    amend: set[str] = set()
    signoff_rel = _relpath(brief_dir / "SIGNOFF", repo)
    if signoff_rel in changed_set:
        for line in gitutil.added_lines(repo, signoff_rel, rng):
            if (m := CONFORMS_RE.match(line)):
                conforms.add(m.group(1))
            elif (m := AMEND_RE.match(line)):
                amend.add(m.group(1))

    bad_refs: list[tuple[str, str]] = []
    for f in changed:
        if _is_brief_path(f):
            continue
        for line in gitutil.added_lines(repo, f, rng):
            for r in find_refs(line):
                try:
                    resolve(r, brief_dir)
                except Exception as e:  # ResolveError / ValueError
                    bad_refs.append((str(r), str(e)))

    return evaluate(changed, locked_edits, index, conforms, amend, bad_refs)


# Back-compat alias: staged check is `check(..., base=None)`.
check_staged = check
