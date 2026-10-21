"""`brief triage`: let a System One model clear the sign-off asks it is confident about.

It never touches the gate. It reads the asks `brief check` would raise, asks the model
whether each change cuts against its decision, and for an ask below the threshold writes
the `conforms` line itself, tagged with the score, so the gate passes for the usual reason
and every model verdict is on record in SIGNOFF. Without the optional model (no
`brief[s1]` or no key) it does nothing and every ask stays.

`triage_amendments` (`brief triage --amendments`) asks, per pending-ratification on a PR,
whether the change should wait for the owner's eyes. When every amendment is below the
threshold, the PR is `auto-ratifiable`; anything else, including no opinion, escalates
(`needs-ratification`). The merge is the ratification either way. It never touches the gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import docs, gitutil, s1, verdicts
from .docs import glob_match, load_index
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



# Amendment triage: P(needs the owner's eyes) must sit below this for the model to ratify by
# merging. Tuned on Clef (eval/amend, 93 labeled amendments, 58 a human should see) by
# eval/cutoff.py with a miss (a should-see amendment auto-merged) costing 20 needless reviews:
# Clef's calibrated P reaches 1/21 at 0.25. It clears 15 of the 35 harmless ones and none of
# the 58; Platt puts the miss rate near 0.2 per 100 amendments. A cutoff belongs to a model:
# re-run eval/amend and eval/cutoff.py before trusting it on another one.
REVIEW_THRESHOLD = 0.25
REVIEW_TUNED_ON = "clef"


@dataclass
class AmendmentVerdict:
    doc_id: str
    anchor_id: str
    review: float | None  # P(the owner should see it before it merges)
    model: str = ""
    key: str = ""  # this version of the amendment (`verdicts.amendment_key`)
    escalated: bool = False  # an earlier version was escalated on this PR: a human decides

    @property
    def auto(self) -> bool:
        return not self.escalated and self.review is not None and self.review < REVIEW_THRESHOLD

    @property
    def why(self) -> str:
        if self.escalated:
            return "escalated earlier on this PR: once a human holds an amendment, its revisions stay with them"
        if self.review is None:
            return "no model opinion (model unset, failed, or the change was too large to judge)"
        if self.review >= REVIEW_THRESHOLD:
            return f"the owner should see it (p={self.review:.3f} >= {REVIEW_THRESHOLD})"
        if self.model and self.model.rsplit("/", 1)[-1] != REVIEW_TUNED_ON:
            return f"safe to approve without the owner (cutoff tuned on {REVIEW_TUNED_ON}, not {self.model})"
        return "safe to approve without the owner"


def triage_amendments(repo: Path, brief_dir: Path, base: str | None = None,
                      via: s1.Client | None = None) -> list[AmendmentVerdict]:
    """Ask the model, per pending amendment, whether the change should wait for the owner's
    eyes before it merges. Writes nothing; `verdict`
    turns the answers into auto-ratifiable or escalate. Any missing opinion escalates, and so
    does any anchor this PR already escalated (any version): revising an amendment a human
    holds must not turn it into one CI merges on the model's word."""
    repo, brief_dir = repo.resolve(), brief_dir.resolve()
    pend = [v for v in check(repo, brief_dir, base) if v.kind == "pending-ratification"]
    if not pend:
        return []
    client = via or s1.client()
    rng = gitutil.merge_base(repo, base) if base else None
    log = (brief_dir / verdicts.RECORDS).relative_to(repo).as_posix()
    before = set(gitutil.content_at(repo, log, rng or "HEAD").splitlines())
    held = {r.anchor for ln in gitutil.content_after(repo, log, rng).splitlines()
            if ln not in before and (r := verdicts.parse_line(ln))}
    index = {d.doc_id: d for d in load_index(brief_dir)}
    changed = gitutil.changed_files(repo, rng)
    out = []
    for v in pend:
        review = None
        model = ""
        d = index.get(v.doc_id)
        amendment = gitutil.content_after(
            repo, (brief_dir / "amendments" / f"{v.anchor_id}.md").relative_to(repo).as_posix(), rng)
        anchor = d.anchor(v.anchor_id) if d else None
        key = verdicts.amendment_key(amendment, anchor.hash if anchor else "")
        if client and d:
            # The globs before the edit count too: an amendment that drops a glob must not hide
            # the code it changes under that glob from the model.
            globs = set(d.related_code) | set(_baseline_globs(repo, v.files[0], rng or "HEAD", d.project))
            code = [f for f in changed if any(glob_match(g, f) for g in globs)]
            edit = gitutil.diff(repo, v.files, rng)
            change = gitutil.diff(repo, code, rng) if code else ""
            if _has_body(edit) and len(edit) + len(change) + len(amendment) <= MAX_DIFF_CHARS:
                a = s1.decide(s1.amendment_state(edit, amendment, change, d.related_code),
                              {"review": s1.review_question()}, via=client)
                review = s1.noul_p(a, "review")
                if a:
                    model = next((x.model for x in a.values() if x.model), "") or s1.model_name()
        out.append(AmendmentVerdict(v.doc_id, v.anchor_id, review, model, key, v.anchor_id in held))
    return out


def _baseline_globs(repo: Path, path: str, ref: str, project: str) -> list[str]:
    try:
        return docs.parse_text(gitutil.content_at(repo, path, ref), Path(path), project).related_code
    except docs.DocError:
        return []


def verdict(rated: list[AmendmentVerdict]) -> dict:
    """The PR-level call: `auto-ratifiable` only when every pending amendment is, else
    `escalate`; `none` when nothing is pending. `stamp` (`s1 <model> p=<max>`) is the
    `ratified_by` prefix of a model-made merge: CI's automerge job merges on `auto-ratifiable`
    and `ratify --pending --triage` records the model as the ratifier."""
    if not rated:
        return {"verdict": "none", "stamp": "", "amendments": []}
    auto = all(a.auto for a in rated)
    stamp = ""
    if auto:
        models = sorted({a.model for a in rated})
        stamp = f"s1 {','.join(models)} p={max(a.review for a in rated):.3f}"
    return {
        "verdict": "auto-ratifiable" if auto else "escalate",
        "stamp": stamp,
        "amendments": [
            {"doc_id": a.doc_id, "anchor_id": a.anchor_id, "review": a.review,
             "model": a.model, "auto": a.auto, "why": a.why, "key": a.key}
            for a in rated
        ],
    }
