"""Resolve a doc:// ref to an exact file/anchor — across revisions, with stale detection.

Filesystem-first: `@current`/`@draft` → the live doc; `@latest`/`@stable` → the aliased
revision (falling back to the live draft until first publish); `@NNNN` → a frozen version
file. A pinned `@NNNN` is *stale* if its anchor's hash differs from the latest revision's.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from . import versions
from .docs import Anchor, Decision, load_index, parse_doc
from .refs import DocRef


class ResolveError(Exception):
    pass


@dataclass
class ResolvedRef:
    ref: str
    project: str
    doc_id: str
    rev: str
    anchor: str | None
    path: str
    start_line: int | None
    end_line: int | None
    title: str | None
    body: str | None
    hash: str | None
    stale: bool | None = None
    stale_since: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _resolve_file(brief_dir: Path, decision: Decision, rev: str) -> tuple[Path, str]:
    if rev in ("current", "draft"):
        return decision.path, "current"
    if rev in ("latest", "stable"):
        n = versions.load_aliases(brief_dir).get(decision.doc_id, {}).get(rev)
        if n is None:
            return decision.path, "current"  # unpublished (or no stable) → live draft
        return versions.version_path(brief_dir, decision.doc_id, int(n)), f"{int(n):04d}"
    try:
        n = int(rev)
    except ValueError:
        raise ResolveError(f"unknown revision/alias @{rev}")
    vf = versions.version_path(brief_dir, decision.doc_id, n)
    if not vf.exists():
        raise ResolveError(f"revision @{n:04d} not published for {decision.doc_id}")
    return vf, f"{n:04d}"


def _stale(brief_dir: Path, decision: Decision, rev_label: str, anchor: Anchor | None) -> tuple[bool | None, str | None]:
    if anchor is None or not rev_label.isdigit():
        return None, None  # only a concrete pinned revision can be stale
    n = int(rev_label)
    latest = versions.latest_rev(brief_dir, decision.doc_id)
    if latest is None or latest <= n:
        return False, None
    latest_anchor = parse_doc(
        versions.version_path(brief_dir, decision.doc_id, latest), decision.project
    ).anchor(anchor.anchor_id)
    if latest_anchor is None or latest_anchor.hash != anchor.hash:
        return True, f"{latest:04d}"
    return False, None


def resolve(ref: str | DocRef, brief_dir: Path) -> ResolvedRef:
    r = ref if isinstance(ref, DocRef) else DocRef.parse(ref)
    index = load_index(brief_dir)
    decision = next((d for d in index if d.doc_id == r.doc_id), None)
    if decision is None:
        known = ", ".join(d.doc_id for d in index) or "<none>"
        raise ResolveError(f"unknown doc-id {r.doc_id!r} (have: {known})")

    file_path, rev_label = _resolve_file(brief_dir, decision, r.rev)
    parsed = decision if file_path == decision.path else parse_doc(file_path, decision.project)

    anchor = None
    if r.anchor:
        anchor = parsed.anchor(r.anchor)
        if anchor is None:
            have = ", ".join(a.anchor_id for a in parsed.anchors) or "<none>"
            raise ResolveError(f"unknown anchor #{r.anchor} in {decision.doc_id}@{rev_label} (have: {have})")

    stale, stale_since = _stale(brief_dir, decision, rev_label, anchor)
    return ResolvedRef(
        ref=str(r),
        project=decision.project,
        doc_id=decision.doc_id,
        rev=rev_label,
        anchor=r.anchor,
        path=str(file_path),
        start_line=anchor.start_line if anchor else None,
        end_line=anchor.end_line if anchor else None,
        title=anchor.title if anchor else parsed.meta.get("title"),
        body=anchor.body if anchor else None,
        hash=anchor.hash if anchor else None,
        stale=stale,
        stale_since=stale_since,
    )
