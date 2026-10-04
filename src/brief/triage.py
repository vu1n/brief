"""`brief triage`: let a System One model clear the sign-off asks it is confident about.

It never touches the gate. It reads the asks `brief check` would raise, asks the model
whether each change cuts against its decision, and for an ask below the threshold writes
the `conforms` line itself, tagged with the score, so the gate passes for the usual reason
and every model verdict is on record in SIGNOFF. Without the optional model (no
`brief[s1]` or no key) it does nothing and every ask stays.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import gitutil, s1
from .docs import load_index
from .gate import check

# eval/s1 (Jev 1.13, 281 agent diffs): at 0.1 every one of 54 violations kept its ask and
# 97% of conforming asks cleared; the lowest-scoring violation sat at 0.21. Raise it only
# with a re-run of that eval.
THRESHOLD = 0.1
# Past this the model would judge a truncated change; leave those asks to the agent.
MAX_DIFF_CHARS = 60_000


@dataclass
class Verdict:
    doc_id: str
    anchor_id: str
    p: float | None  # None: no opinion (model unavailable, failed, or diff too large)
    cleared: bool


def triage(repo: Path, brief_dir: Path, base: str | None = None,
           threshold: float = THRESHOLD, via: s1.Client | None = None) -> list[Verdict]:
    asks = [v for v in check(repo, brief_dir, base) if v.kind == "needs-conformance"]
    if not asks:
        return []
    client = via or s1.client()
    rng = gitutil.merge_base(repo, base) if base else None
    index = {d.doc_id: d for d in load_index(brief_dir)}
    model = os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-latest")
    verdicts, lines = [], []
    for v in asks:
        anchor = index[v.doc_id].anchor(v.anchor_id) if v.doc_id in index else None
        change = gitutil.diff(repo, v.files, rng)
        p = None
        if client and anchor and change and len(change) <= MAX_DIFF_CHARS:
            a = s1.decide(s1.conflict_state(f"{anchor.title}. {anchor.body}", change),
                          {"conflict": s1.conflict_question()}, via=client)
            p = a["conflict"].p if a and "conflict" in a else None
        cleared = p is not None and p < threshold
        if cleared:
            lines.append(f"{v.anchor_id} conforms: (s1 {model} p={p:.2f}) model rated the "
                         f"change unlikely to cut against the decision\n")
        verdicts.append(Verdict(v.doc_id, v.anchor_id, p, cleared))
    if lines:
        signoff = brief_dir / "SIGNOFF"
        text = signoff.read_text() if signoff.exists() else ""
        signoff.write_text(text + ("" if not text or text.endswith("\n") else "\n") + "".join(lines))
        if base is None:  # staged mode: the gate reads SIGNOFF from the index
            gitutil._git(repo, "add", "--", str(signoff.relative_to(repo)))
    return verdicts
