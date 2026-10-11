"""Ratify — the authorized path to change a locked decision (the L3 mechanical bit).

Default workflow: the amendment PR carries `.brief/amendments/<anchor>.md` and the
proposed decision text (the gate reports it as pending-ratification), a human reviews and
merges it, and the CI job `brief init --ci` writes runs `ratify_pending` on the default
branch, which publishes the revision and archives the amendment as ratified by the merger.
An amendment CI escalated is published only once a maintainer `/ratify`d it in its PR
thread (`verdicts`, `threads`). By hand, a human edits the live decision and runs `brief ratify <anchor>`.

Authority is the human merging the PR / running it — `brief` makes ratification an
explicit, structured, reviewable act. The gate exempts the decision edit only when the
change carries this function's full output: the new archived amendment (stamped
`ratified_rev`) and the new published revision equal to the live doc (see
`gate._ratified`). A bare file in the archive is not enough. It still cannot locally
prevent a hand-forged copy of that output; CI + human PR review is the backstop.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import verdicts, versions
from .docs import load_index, parse_doc


class RatifyError(Exception):
    pass


@dataclass
class Ratification:
    doc_id: str
    anchor: str
    rev: int
    archived: str


def ratify(brief_dir: Path, anchor_id: str, by: str | None = None) -> Ratification:
    decision = next((d for d in load_index(brief_dir) if d.anchor(anchor_id)), None)
    if decision is None:
        raise RatifyError(f"no decision with anchor {anchor_id!r}")
    proposal = brief_dir / "amendments" / f"{anchor_id}.md"
    if not proposal.exists():
        raise RatifyError(f"no amendment proposal at {proposal}")

    rev = versions.publish(brief_dir, decision.doc_id)
    return _archive(brief_dir, decision.doc_id, anchor_id, rev, by)


def _archive(brief_dir: Path, doc_id: str, anchor_id: str, rev: int, by: str | None) -> Ratification:
    proposal = brief_dir / "amendments" / f"{anchor_id}.md"
    archive = brief_dir / "amendments" / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    dest = archive / f"{anchor_id}-v{rev:04d}.md"
    dest.write_text(
        proposal.read_text(encoding="utf-8")
        + f"\n\n---\nratified_rev: {rev:04d}\nratified_by: {by or 'unknown'}\n",
        encoding="utf-8",
    )
    proposal.unlink()
    return Ratification(doc_id=doc_id, anchor=anchor_id, rev=rev, archived=str(dest))


def ratify_pending(brief_dir: Path, by: str | None = None, held: list[str] | None = None) -> list[Ratification]:
    """Ratify every amendment whose decision the tree already changed: the live doc differs
    from its latest published revision. Run after a merge (the merge is the ratification).
    Archives the amendments for the anchors that changed, or every amendment of the doc if
    only its frontmatter did. A proposal whose decision text is unchanged (still waiting for
    one), a never-published doc, and an edit with an unamended anchor are left: the gate
    never passes those as pending, so they are not a merge's to ratify.

    An amendment CI escalated (`.brief/RATIFICATIONS`) needs a maintainer's `/ratify` of this
    version; one escalated-but-unanswered or rejected holds its whole doc unpublished, and
    is appended to `held` as `doc#anchor: <state>`. The PR gate blocks both, so this only
    happens on a merge past a red gate; a human then runs `brief ratify <anchor>`. A
    ratified anchor is stamped with the maintainer and their comment, then `by`."""
    out: list[Ratification] = []
    log = brief_dir / verdicts.RECORDS
    records = verdicts.parse(log.read_text(encoding="utf-8")) if log.exists() else []
    for d in load_index(brief_dir):
        rev = versions.latest_rev(brief_dir, d.doc_id)
        frozen = versions.version_path(brief_dir, d.doc_id, rev) if rev else None
        if frozen is None or not frozen.exists():
            continue
        if frozen.read_text(encoding="utf-8") == d.path.read_text(encoding="utf-8"):
            continue
        old = {a.anchor_id: a.hash for a in parse_doc(frozen, d.project).anchors}
        new = {a.anchor_id: a.hash for a in d.anchors}
        ids = sorted(old.keys() | new.keys())
        moved = [a for a in ids if old.get(a) != new.get(a)]
        props = [a for a in (moved or ids) if (brief_dir / "amendments" / f"{a}.md").exists()]
        if not props or (moved and len(props) < len(moved)):
            continue  # an anchor changed without its amendment: not what the gate lets merge
        stamps: dict[str, str | None] = {}
        blocked = []
        for a in props:
            anchor = d.anchor(a)
            text = (brief_dir / "amendments" / f"{a}.md").read_text(encoding="utf-8")
            r = verdicts.state(records, a, verdicts.amendment_key(text, anchor.hash if anchor else ""))
            if r is not None and r.kind != "ratified":
                blocked.append(f"{d.doc_id}#{a}: {r.kind}")
            stamps[a] = by if r is None else f"{r.who} via /ratify ({r.url}); {by or 'unknown'}"
        if blocked:
            if held is not None:
                held += blocked
            continue  # one unanswered or rejected anchor holds the whole doc
        rev = versions.publish(brief_dir, d.doc_id)
        out += [_archive(brief_dir, d.doc_id, a, rev, stamps[a]) for a in props]
    return out
