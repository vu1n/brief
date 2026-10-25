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
6. pending-ratification — a locked decision edit that carries its amendment: every anchor
                     the edit changes has `.brief/amendments/<anchor>.md`, the doc is
                     published and stays where it is, and no revision is minted by hand.
                     Merging the PR is the ratification (CI's `brief ratify --pending`
                     publishes it), so on a PR range it does not block. Staged on a
                     feature branch it does not block either: the commit goes to a PR,
                     whose merge ratifies it. Staged on the default branch (or a detached
                     HEAD) it blocks: a commit there can't ratify, and nothing would
                     review it. An edit without its amendment stays ratified-edit.
                     Once CI escalated it to a human (`escalated` in .brief/RATIFICATIONS
                     for this version of the amendment), it blocks until a maintainer
                     replies `/ratify` in its PR thread.
7. amendment-rejected — a maintainer replied `/reject` to this version of the amendment.
                     Revising the amendment (or the decision text) is a new version, which
                     re-escalates; withdrawing it removes the pending edit.
8. untrusted-verdict — a .brief/RATIFICATIONS line added outside a github-actions[bot]
                     commit, or any line removed: the log is the bot's, append-only. (CI's
                     `brief thread verify` also checks each verdict against the bot's own
                     PR comment, since a commit's identity is self-asserted.)
9. proposal-only   — on a PR range, a `.brief/amendments/<anchor>.md` this change adds or
                     edits for a locked decision whose text the change leaves alone. The
                     merge is the ratification only when the PR carries the proposed
                     decision text, so merging this would ratify nothing and leave a human
                     to run `brief ratify` by hand afterwards. Put the text in the PR.

Whether code *conforms* to a standing decision is semantic (L1 sampling / L2 tests);
the gate does not attempt it. But because the decision is read-only, a "conforms"
claim is now falsifiable against a fixed target instead of one the author can edit.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import docs, gitutil, verdicts, versions
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


_COMMENT_START = ("//", "#", "/*", "*", "--", "<!--", ";")
# `#` lines that are code, not comments: Rust attributes, shebangs, C preprocessor
_HASH_CODE = ("#[", "#!", "#include", "#define", "#if", "#else", "#elif", "#endif", "#pragma", "#import", "#undef")


def _is_comment(line: str) -> bool:
    s = line.strip()
    return not s or (s.startswith(_COMMENT_START) and not s.startswith(_HASH_CODE))


def _comment_only_change(repo: Path, path: str, rng: str | None) -> bool:
    """True if every added and removed line of a governed file is a comment (or blank):
    wiring a `// Context:` ref, rewording a why-comment. Comments can't violate a
    behavioral invariant, so the file is exempt from needs-conformance. One code line
    re-arms the gate, and so does deleting a ref (that unwires a decision, which
    `_context_scope` asks about). broken-ref is still checked separately."""
    added = gitutil.added_lines(repo, path, rng)
    removed = gitutil.removed_lines(repo, path, rng)
    if not added and not removed:
        return False
    if not all(_is_comment(line) for line in added + removed):
        return False
    return not _unwired(added, removed)


def _ref_keys(lines: list[str]) -> set[tuple[str, str | None]]:
    return {(r.doc_id, r.anchor) for line in lines for r in find_refs(line)}


def _unwired(added: list[str], removed: list[str]) -> set[tuple[str, str | None]]:
    """(doc_id, anchor) refs the change deletes and doesn't put back (a reword keeps them)."""
    return _ref_keys(removed) - _ref_keys(added)


@dataclass
class Violation:
    kind: str  # ratified-edit | needs-conformance | amendment-required | broken-ref | empty-glob
    #            | pending-ratification | amendment-rejected | untrusted-verdict | proposal-only
    doc_id: str = ""
    anchor_id: str = ""
    files: list[str] = field(default_factory=list)
    detail: str = ""
    blocking: bool = True  # only pending-ratification (on a PR range or a feature branch) is reported without blocking


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
    pending: dict[str, list[str]] | None = None,
) -> list[Violation]:
    """Pure core. `locked_edits` = doc_ids of locked decisions modified in this commit.
    `exempt` = code files whose change is ref-only (comment pointer, no behavior) and so
    does not trigger needs-conformance. `scope` narrows a governed file change to the
    anchors it actually touches (default: all of them). `pending` = doc_id -> anchors whose
    amendment this change carries along with the decision edit (see `_pending`); their
    `amend-proposed` is answered by the merge, so it raises no amendment-required."""
    exempt = exempt or set()
    pending = pending or {}
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

    for doc_id, anchors in sorted(pending.items()):
        for a in anchors:
            violations.append(
                Violation(
                    kind="pending-ratification",
                    doc_id=doc_id,
                    anchor_id=a,
                    detail="decision edit carries its amendment — merging the PR ratifies it",
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
            if a.anchor_id in pending.get(d.doc_id, ()):
                continue  # reported once, as pending-ratification
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


def _amendment_rel(repo: Path, brief_dir: Path, anchor_id: str) -> str:
    return _relpath(brief_dir / "amendments" / f"{anchor_id}.md", repo)


def _pending(
    repo: Path,
    brief_dir: Path,
    index: list[Decision],
    locked_paths: dict[str, str],
    changed: list[str],
    baseline_ref: str,
    rng: str | None,
) -> dict[str, list[str]]:
    """doc_id -> amended anchors, for each locked edit that is an amendment awaiting the
    merge that ratifies it. Fails closed (stays ratified-edit) when the doc moved or was
    deleted, was never published, has a revision minted or `latest` moved in this change
    (only ratification publishes), its baseline won't parse, or any anchor the edit adds,
    removes or rewrites lacks `.brief/amendments/<anchor>.md`: amending anchor A can't
    cover a quiet edit of B."""
    by_id = {d.doc_id: d for d in index}
    out: dict[str, list[str]] = {}
    if _relpath(versions.aliases_file(brief_dir), repo) in changed:
        return out  # `latest` is ratification's to move
    for doc_id, path in sorted(locked_paths.items()):
        d = by_id.get(doc_id)
        if d is None or _relpath(d.path, repo) != path:
            continue
        vdir = _relpath(versions.versions_dir(brief_dir, doc_id), repo) + "/"
        if not gitutil.files_at(repo, baseline_ref, vdir) or any(f.startswith(vdir) for f in changed):
            continue
        try:
            before = docs.parse_text(gitutil.content_at(repo, path, baseline_ref), Path(path), d.project)
        except docs.DocError:
            continue
        old = {a.anchor_id: a.hash for a in before.anchors}
        new = {a.anchor_id: a.hash for a in d.anchors}
        moved = {a for a in old.keys() | new.keys() if old.get(a) != new.get(a)}
        amended = {
            a for a in old.keys() | new.keys()
            if gitutil.content_after(repo, _amendment_rel(repo, brief_dir, a), rng)
        }
        if amended and moved <= amended:
            # A frontmatter-only edit (status, related_code) is covered by any amendment.
            out[doc_id] = sorted(moved or amended)
    return out


def _proposal_only(
    repo: Path,
    brief_dir: Path,
    index: list[Decision],
    changed: list[str],
    pending: dict[str, list[str]],
    rng: str | None,
) -> list[Violation]:
    """Proposals this PR adds or edits that its merge can't ratify: no decision edit
    carries them (see `_pending`). An anchor of an unlocked doc is left alone (a draft
    needs no amendment); one no doc has is flagged, since only an edit adding it could
    carry it."""
    covered = {a for anchors in pending.values() for a in anchors}
    unlocked = {a.anchor_id for d in index if not _is_locked(d.meta.get("status")) for a in d.anchors}
    prefix = _relpath(brief_dir / "amendments", repo) + "/"
    out: list[Violation] = []
    for f in changed:
        name = f[len(prefix):] if f.startswith(prefix) else ""
        if not name.endswith(".md") or "/" in name or not gitutil.content_after(repo, f, rng):
            continue  # not a live proposal (archived, withdrawn, or elsewhere)
        anchor = name[:-3]
        if anchor in covered or anchor in unlocked:
            continue
        doc = next((d.doc_id for d in index if d.anchor(anchor)), "")
        out.append(Violation(
            kind="proposal-only", doc_id=doc, anchor_id=anchor, files=[f],
            detail="amendment without its decision text — merging this PR would ratify nothing",
        ))
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
    locked_paths: dict[str, str] = {}
    frozen_edits: set[str] = set()  # never exempt: ratify adds a revision, it never rewrites one
    docs_prefix = f"{_relpath(brief_dir, repo)}/docs/"
    for path in gitutil.files_at(repo, baseline_ref, docs_prefix):
        if path not in changed_set or not path.endswith(".md"):
            continue
        before = gitutil.content_at(repo, path, baseline_ref)
        if "versions" in path[len(docs_prefix):].split("/"):
            frozen_edits.add(path.split("/")[-3])  # docs/<doc-id>/versions/vNNNN.md
        elif _is_locked(docs.status_of(before)):
            locked_paths[docs.doc_id_of(before, Path(path))] = path

    locked_edits = set(locked_paths)
    locked_edits -= _ratified(repo, brief_dir, index, changed, changed_set, baseline_ref, rng)
    pending = _pending(
        repo, brief_dir, index, {k: v for k, v in locked_paths.items() if k in locked_edits},
        changed, baseline_ref, rng,
    )
    locked_edits -= set(pending)
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
        if _comment_only_change(repo, f, rng):
            exempt.add(f)

    violations = evaluate(
        changed, locked_edits, index, conforms, amend, bad_refs, exempt,
        scope=_context_scope(repo, rng), pending=pending,
    )
    staged_blocks = base is None and gitutil.on_default_branch(repo)
    for v in violations:
        if v.kind == "pending-ratification":
            v.files = [_relpath(next(d.path for d in index if d.doc_id == v.doc_id), repo)]
            v.blocking = staged_blocks  # a commit can't ratify; only a PR's merge does
    if base:
        violations += _proposal_only(repo, brief_dir, index, changed, pending, rng)
    violations += _verdict_log(repo, brief_dir, index, violations, changed_set, base, rng)
    return violations + _empty_globs(repo, brief_dir, index, base)


def _verdict_log(
    repo: Path,
    brief_dir: Path,
    index: list[Decision],
    violations: list[Violation],
    changed_set: set[str],
    base: str | None,
    rng: str | None,
) -> list[Violation]:
    """Apply .brief/RATIFICATIONS to the pending amendments (mutating their violations) and
    report lines the bot didn't write. See `verdicts` for the format and the trust rule."""
    rel = _relpath(brief_dir / verdicts.RECORDS, repo)
    out: list[Violation] = []
    untrusted: set[str] = set()
    if rel in changed_set:
        prov = verdicts.provenance(repo, rel, base, rng)
        untrusted = set(prov.untrusted)
        out += [Violation(kind="untrusted-verdict", files=[rel],
                          detail=f"added outside a github-actions[bot] commit: {ln}") for ln in prov.untrusted]
        out += [Violation(kind="untrusted-verdict", files=[rel],
                          detail=f"removed (the log is append-only): {ln}") for ln in prov.removed]
    text = gitutil.content_after(repo, rel, rng)
    records = verdicts.parse("\n".join(ln for ln in text.splitlines() if ln not in untrusted))
    if not records:
        return out
    by_id = {d.doc_id: d for d in index}
    for v in violations:
        if v.kind != "pending-ratification":
            continue
        a = by_id[v.doc_id].anchor(v.anchor_id)
        key = verdicts.amendment_key(
            gitutil.content_after(repo, _amendment_rel(repo, brief_dir, v.anchor_id), rng), a.hash if a else "")
        r = verdicts.state(records, v.anchor_id, key)
        if r is None:
            continue
        if r.kind == "rejected":
            v.kind, v.blocking = "amendment-rejected", True
            v.detail = (f"rejected by {r.who} ({r.url}): {r.reason} — revise the amendment (a new "
                        "version re-escalates) or withdraw it")
        elif r.kind == "escalated":
            v.blocking = True
            v.detail = "escalated to a human: waiting for a maintainer's /ratify in its PR thread"
        else:
            v.detail = f"ratified by {r.who} in its PR thread ({r.url}); merging publishes it"
    return out


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
        if _is_comment(line):
            base = next(
                (j for j in range(i + 1, len(lines)) if not _is_comment(lines[j])),
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
    cache: dict[str, tuple[str, set[int], set[tuple[str, str | None]]]] = {}

    def scope(d: Decision, f: str) -> set[str] | None:
        if f not in cache:
            cache[f] = (
                gitutil.content_after(repo, f, rng),
                gitutil.changed_lines(repo, f, rng),
                _unwired(gitutil.added_lines(repo, f, rng), gitutil.removed_lines(repo, f, rng)),
            )
        text, changed, unwired = cache[f]
        spans = ref_blocks(text, d.doc_id)
        if not spans:
            return None
        # deleting a ref unwires that anchor here: it needs the sign-off its block would have
        hit: set[str] = set()
        for doc_id, anchor in unwired:
            if doc_id == d.doc_id:
                if anchor is None:
                    return None
                hit.add(anchor)
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
