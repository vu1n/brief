"""`brief triage`: let a System One model clear the sign-off asks it is confident about.

It never touches the gate. It reads the asks `brief check` would raise, asks the model
whether each change cuts against its decision, and for an ask below the threshold writes
the `conforms` line itself, tagged with the score, so the gate passes for the usual reason
and every model verdict is on record in SIGNOFF. Without the optional model (no
`brief[s1]` or no key) it does nothing and every ask stays.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import gitutil, s1
from .docs import load_index
from .gate import CONFORMS_RE, check

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
    p: float | None  # None: no opinion (model unavailable, failed, or no judgeable diff)
    cleared: bool


def _has_body(diff: str) -> bool:
    """A diff the model can judge: at least one added or removed content line."""
    return any(ln[:1] in "+-" and not ln.startswith(("+++", "---")) for ln in diff.splitlines())


def triage(repo: Path, brief_dir: Path, base: str | None = None,
           threshold: float = THRESHOLD, via: s1.Client | None = None) -> list[Verdict]:
    repo, brief_dir = repo.resolve(), brief_dir.resolve()
    asks = [v for v in check(repo, brief_dir, base) if v.kind == "needs-conformance"]
    if not asks:
        return []
    client = via or s1.client()
    rng = gitutil.merge_base(repo, base) if base else None
    index = {d.doc_id: d for d in load_index(brief_dir)}
    verdicts, models = [], {}
    for v in asks:
        anchor = index[v.doc_id].anchor(v.anchor_id) if v.doc_id in index else None
        change = gitutil.diff(repo, v.files, rng) if client and anchor else ""
        p = None
        if _has_body(change) and len(change) <= MAX_DIFF_CHARS:
            a = s1.decide(s1.conflict_state(f"{anchor.title}. {anchor.body}", change),
                          {"conflict": s1.conflict_question()}, via=client)
            p = s1.noul_p(a, "conflict")
            if p is not None:
                models[v.anchor_id] = a["conflict"].model or s1.model_name()
        verdicts.append(Verdict(v.doc_id, v.anchor_id, p, p is not None and p < threshold))

    # The gate matches a conforms line on the bare anchor id, across every doc: clear an id
    # only when every ask that shares it is below the threshold.
    for v in verdicts:
        v.cleared = v.cleared and all(o.cleared for o in verdicts if o.anchor_id == v.anchor_id)
    signoff = brief_dir / "SIGNOFF"
    rel = signoff.relative_to(repo).as_posix()
    lines = {}
    for v in verdicts:
        if v.cleared and v.anchor_id not in lines:
            p = max(o.p for o in verdicts if o.anchor_id == v.anchor_id)
            lines[v.anchor_id] = (f"{v.anchor_id} conforms: (s1 {models[v.anchor_id]} p={p:.3f}) "
                                  f"model rated the change unlikely to cut against the decision\n")
    if lines:
        on_disk = signoff.read_text() if signoff.exists() else ""
        signoff.write_text(_append(on_disk, lines))
        if base is None:
            # Staged mode: the gate reads SIGNOFF from the index. Add only these lines to the
            # staged copy, so an unstaged line of the agent's never rides along unreviewed.
            gitutil.stage_content(repo, rel, _append(gitutil.staged_content(repo, rel), lines))
    return verdicts


def _append(text: str, lines: dict[str, str]) -> str:
    """`text` plus the lines for anchors it doesn't already sign off (re-runs don't stack)."""
    have = {m.group(1) for ln in text.splitlines() if (m := CONFORMS_RE.match(ln))}
    new = "".join(ln for a, ln in lines.items() if a not in have)
    return text + ("" if not text or not new or text.endswith("\n") else "\n") + new
