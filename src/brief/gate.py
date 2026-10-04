"""L0 governance gate — separation of powers.

A ratified decision is a CONSTRAINT the coding loop is checked against, not state
the coding loop may rewrite. So the gate enforces:

1. ratified-edit   — a coding commit must NOT modify, delete, or rename a locked
                     (active/ratified) decision, nor touch a published revision.
                     A baseline doc whose frontmatter won't parse counts as locked
                     (fail closed: a YAML repair can't smuggle in a rule change).
                     To change one, propose an amendment for human ratification. (This is the fix for "reversal by fiat": the
                     constrained party cannot edit the constraint to pass.)
2. needs-conformance — when governed code changes, the author must record either
                     `<anchor> conforms: <why>` (code still satisfies the decision)
                     or `<anchor> amend-proposed: <why>` in .brief/SIGNOFF.
                     Exempt: a change that only ADDS doc-ref comment lines (e.g. wiring a
                     `// Context:` back-ref) is a pointer, not behavior, so it needs no
                     sign-off. Any non-ref added line or any removal re-arms the check.
3. amendment-required — `amend-proposed` blocks the commit: code that needs a
                     ratified decision changed cannot land until the amendment is
                     ratified. (A correct *escalation*, not a rule violation.)
4. broken-ref      — a doc:// ref added to code that does not resolve.
5. empty-glob      — a feature-map `paths:` glob that matches no tracked file. The map is
                     how a diff finds its features; a dead glob silently drops that code
                     from it, so a move or delete must update the map in the same change.

Whether code *conforms* to a standing decision is semantic (L1 sampling / L2 tests);
the gate does not attempt it. But because the decision is read-only, a "conforms"
claim is now falsifiable against a fixed target instead of one the author can edit.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import docs, gitutil, versions
from .docs import Decision, glob_match, load_index
from .features import empty_globs, load_features
from .refs import find_refs
from .resolve import resolve

LOCKED_STATUSES = {"active", "ratified"}

CONFORMS_RE = re.compile(r"^\s*([a-z0-9][a-z0-9-]*)\s+conforms\b")
AMEND_RE = re.compile(r"^\s*([a-z0-9][a-z0-9-]*)\s+amend-proposed\b")


def _is_brief_path(p: str) -> bool:
    return p.startswith(".brief/") or "/.brief/" in f"/{p}"


def _is_locked(status: str | None) -> bool:
    return status == docs.UNPARSEABLE or (status or "").lower() in LOCKED_STATUSES


def _ref_only_change(repo: Path, path: str, rng: str | None) -> bool:
    """True if a governed file's change is *only* the addition of doc-ref comment lines
    (e.g. `// Context: doc://…`) and removes nothing. Such an edit adds a pointer, not
    behavior — it cannot violate a behavioral invariant — so it is exempt from
    needs-conformance. Any non-ref added line, or any removal, re-arms the gate, so a real
    change can't hide behind a ref. (broken-ref is still checked separately.)"""
    added = gitutil.added_lines(repo, path, rng)
    if not added:
        return False
    if any(not find_refs(line) for line in added):
        return False
    return not gitutil.removed_lines(repo, path, rng)


@dataclass
class Violation:
    kind: str  # ratified-edit | needs-conformance | amendment-required | broken-ref | empty-glob
    doc_id: str = ""
    anchor_id: str = ""
    files: list[str] = field(default_factory=list)
    detail: str = ""


# anchors of `doc` a change to `file` touches: None = all of them, empty = none
Scope = Callable[[Decision, str], "set[str] | None"]


def requires_signoff(d: Decision) -> bool:
    """Sign-off is opt-in per decision (`signoff: required`). Every locked decision is
    read-only regardless; sign-off is for the few where silent drift in code is costly."""
    v = d.meta.get("signoff")
    return v is True or str(v).lower() == "required"


def evaluate(
    changed_files: list[str],
    locked_edits: set[str],
    index: list[Decision],
    conforms: set[str],
    amend_proposed: set[str],
    bad_refs: list[tuple[str, str]] | None = None,
    exempt: set[str] | None = None,
    scope: Scope | None = None,
) -> list[Violation]:
    """Pure core. `locked_edits` = doc_ids of locked decisions modified in this commit.
    `exempt` = code files whose change is ref-only (comment pointer, no behavior) and so
    does not trigger needs-conformance. `scope` narrows a governed file change to the
    anchors it actually touches (default: all of them)."""
    exempt = exempt or set()
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
        signoff = requires_signoff(d)
        if not signoff and not any(a.anchor_id in amend_proposed for a in d.anchors):
            continue  # read-only, but its governed code changes without a sign-off
        governed: list[str] = []
        touched: set[str] | None = set()
        for f in code_changes:
            if f in exempt or not any(glob_match(g, f) for g in d.related_code):
                continue
            hit = scope(d, f) if scope else None
            if hit is not None and not hit:
                continue
            governed.append(f)
            touched = None if hit is None or touched is None else touched | hit
        if not governed:
            continue
        for a in d.anchors:
            if touched is not None and a.anchor_id not in touched:
                continue
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
            elif signoff:
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


ARCHIVE_RE = re.compile(r"^(?P<anchor>[a-z0-9][a-z0-9-]*)-v(?P<rev>\d+)\.md$")


def _ratified(
    repo: Path,
    brief_dir: Path,
    index: list[Decision],
    changed: list[str],
    changed_set: set[str],
    baseline_ref: str,
    rng: str | None,
) -> set[str]:
    """Doc ids whose locked edit in this change is an authorized ratification (L3), i.e.
    carries what `brief ratify` writes: a NEW archived amendment `<anchor>-vNNNN.md`
    stamped `ratified_rev: NNNN`, plus a NEW frozen `versions/vNNNN.md` of that doc equal
    to its live text. A bare file dropped in the archive is not enough. Hand-forging the
    full set is still possible — authority is the human approving the PR (L3), which is
    why a ratification is only ever exempted alongside its published revision."""
    out: set[str] = set()
    for f in changed:
        m = ARCHIVE_RE.match(f.rsplit("/", 1)[-1])
        if not m or "/amendments/archive/" not in f"/{f}":
            continue
        if gitutil.content_at(repo, f, baseline_ref):
            continue  # pre-existing archive entry: not this change's ratification
        rev = int(m["rev"])
        stamp = re.compile(rf"^ratified_rev:\s*0*{rev}\s*$", re.M)
        if not stamp.search(gitutil.content_after(repo, f, rng)):
            continue
        for d in index:
            if not d.anchor(m["anchor"]):
                continue
            ver = _relpath(versions.version_path(brief_dir, d.doc_id, rev), repo)
            if (
                ver in changed_set
                and not gitutil.content_at(repo, ver, baseline_ref)
                and gitutil.content_after(repo, ver, rng)
                == gitutil.content_after(repo, _relpath(d.path, repo), rng)
            ):
                out.add(d.doc_id)
    return out


def check(repo: Path, brief_dir: Path, base: str | None = None) -> list[Violation]:
    """Evaluate the gate over staged changes (base=None, local) or base..HEAD (CI)."""
    repo = repo.resolve()
    baseline_ref = gitutil.merge_base(repo, base) if base else "HEAD"
    rng = baseline_ref if base else None
    changed = gitutil.changed_files(repo, rng)
    changed_set = set(changed)
    index = load_index(brief_dir)

    # Locked decisions are read from the BASELINE tree, not the working tree: a decision
    # deleted, or renamed aside and demoted, in this change no longer exists in `index`,
    # but its baseline path still shows as changed (changed_files uses --no-renames).
    # Status is read at the baseline too, so flipping it in the same change can't dodge.
    # Published revisions (`versions/vNNNN.md`) are immutable whatever the doc's status.
    locked_edits: set[str] = set()
    frozen_edits: set[str] = set()  # never exempt: ratify adds a revision, it never rewrites one
    docs_prefix = f"{_relpath(brief_dir, repo)}/docs/"
    for path in gitutil.files_at(repo, baseline_ref, docs_prefix):
        if path not in changed_set or not path.endswith(".md"):
            continue
        before = gitutil.content_at(repo, path, baseline_ref)
        if "versions" in path[len(docs_prefix):].split("/"):
            frozen_edits.add(path.split("/")[-3])  # docs/<doc-id>/versions/vNNNN.md
        elif _is_locked(docs.status_of(before)):
            locked_edits.add(docs.doc_id_of(before, Path(path)))

    locked_edits -= _ratified(repo, brief_dir, index, changed, changed_set, baseline_ref, rng)
    locked_edits |= frozen_edits

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
    exempt: set[str] = set()
    for f in changed:
        if _is_brief_path(f):
            continue
        for line in gitutil.added_lines(repo, f, rng):
            for r in find_refs(line):
                try:
                    resolve(r, brief_dir)
                except Exception as e:  # ResolveError / ValueError
                    bad_refs.append((str(r), str(e)))
        # a pure ref-add is a pointer, not behavior → exempt from needs-conformance
        if _ref_only_change(repo, f, rng):
            exempt.add(f)

    violations = evaluate(
        changed, locked_edits, index, conforms, amend, bad_refs, exempt,
        scope=_context_scope(repo, rng),
    )
    return violations + _empty_globs(repo, brief_dir, index, base)


_COMMENT_START = ("//", "#", "/*", "*", "--", "<!--", ";")
_BLOCK_CLOSE = ("}", ")", "]", "end", "else", "elif", "except", "finally", "catch")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def ref_blocks(text: str, doc_id: str) -> list[tuple[int, int, str | None]]:
    """(first, last, anchor) 1-based line spans of the code each `// Context:` ref to
    `doc_id` sits on. A ref in a comment covers the next statement and everything indented
    under it (plus its closing brace); a ref trailing code covers that line's block.
    Language-agnostic by indentation — a heuristic, so callers fall back to the whole file
    when a decision has no ref in it."""
    lines = text.splitlines()
    spans: list[tuple[int, int, str | None]] = []
    for i, line in enumerate(lines):
        anchors = [r.anchor for r in find_refs(line) if r.doc_id == doc_id]
        if not anchors:
            continue
        base = i
        if line.lstrip().startswith(_COMMENT_START):
            base = next(
                (j for j in range(i + 1, len(lines))
                 if lines[j].strip() and not lines[j].lstrip().startswith(_COMMENT_START)),
                i,
            )
        end, ind = base, _indent(lines[base])
        for k in range(base + 1, len(lines)):
            s = lines[k].strip()
            if not s:
                continue
            if _indent(lines[k]) > ind or (_indent(lines[k]) == ind and s.startswith(_BLOCK_CLOSE)):
                end = k
            else:
                break
        spans += [(i + 1, end + 1, a) for a in anchors]
    return spans


def _context_scope(repo: Path, rng: str | None) -> Scope:
    """Scope a governed file change by the decision's `// Context:` refs in that file: only
    a hunk inside a ref's block needs that anchor's sign-off. A file with no ref to the
    decision falls back to every anchor (the decision is unwired there, not unaffected)."""
    cache: dict[str, tuple[str, set[int], list[str]]] = {}

    def scope(d: Decision, f: str) -> set[str] | None:
        if f not in cache:
            cache[f] = (
                gitutil.content_after(repo, f, rng),
                gitutil.changed_lines(repo, f, rng),
                gitutil.removed_lines(repo, f, rng),
            )
        text, changed, removed = cache[f]
        spans = ref_blocks(text, d.doc_id)
        if not spans:
            return None
        # deleting a ref unwires that anchor here: it needs the sign-off its block would have
        hit: set[str] = set()
        for line in removed:
            for r in find_refs(line):
                if r.doc_id == d.doc_id:
                    if r.anchor is None:
                        return None
                    hit.add(r.anchor)
        for first, last, anchor in spans:
            if any(first <= n <= last for n in changed):
                if anchor is None:
                    return None  # a ref to the whole doc covers every anchor
                hit.add(anchor)
        return hit

    return scope


def _empty_globs(repo: Path, brief_dir: Path, index: list[Decision], base: str | None) -> list[Violation]:
    """Feature-map globs matching no file on the change's far side: HEAD in range mode,
    the index when staged. Repo-wide, not diff-scoped — a dead glob is stale whoever made it."""
    feats = load_features(brief_dir, index)
    if not feats:
        return []
    files = gitutil.files_at(repo, "HEAD", ".") if base else gitutil.tracked_files(repo)
    return [
        Violation(
            kind="empty-glob",
            doc_id=f.doc_id,
            anchor_id=f.feature_id,
            detail=f"paths glob {g!r} matches no tracked file — update the feature's paths to where its code lives now",
        )
        for f, g in empty_globs(feats, files)
    ]


# Back-compat alias: staged check is `check(..., base=None)`.
check_staged = check
