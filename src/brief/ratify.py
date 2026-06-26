"""Ratify — the authorized path to change a locked decision (the L3 mechanical bit).

Workflow: a human reviews `.brief/amendments/<anchor>.md` (optionally with the
`brief-review` skill), edits the live decision doc to the new text, then runs
`brief ratify <anchor>`. That publishes a new revision and archives the amendment.

Authority is the human running it / approving the PR — `brief` makes ratification an
explicit, structured, reviewable act (the gate exempts it precisely *because* the
archived amendment is present). It does not, and cannot locally, prevent a forged
ratification; CI + human PR review is the backstop.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import versions
from .docs import load_index


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

    archive = brief_dir / "amendments" / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    dest = archive / f"{anchor_id}-v{rev:04d}.md"
    dest.write_text(
        proposal.read_text(encoding="utf-8")
        + f"\n\n---\nratified_rev: {rev:04d}\nratified_by: {by or 'unknown'}\n",
        encoding="utf-8",
    )
    proposal.unlink()
    return Ratification(doc_id=decision.doc_id, anchor=anchor_id, rev=rev, archived=str(dest))
