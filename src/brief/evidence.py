"""`brief evidence`: what a reviewer needs to judge each pending amendment, with sources.

Advisory only. Nothing here feeds the gate, triage, auto-merge or ratification; it writes
nothing and its output is never read back by brief.

Per amendment, deterministic and exact (the baseline is the merge-base, as in the gate):
- the decision lines removed and added, by line number, and the qualifier words
  (never, only, unless, must, at most...) that left or entered the text;
- the amendment's template sections (What should change / Why / Code that needs it /
  Impact / risk) with line numbers, missing ones, and claims nobody verified ("tests pass");
- governed scope before and after: globs, files that leave governance, and which of
  those this change edits (a narrowing hides them from triage and sign-off);
- linked decisions: explicit `doc://` refs either way, and decisions sharing governed
  files; plus the `// Context:` sites in code that cite the amended anchor.

Optional shadow layer: with a System One model configured (`brief[s1]`, as triage), each
other decision gets P(the edit undermines it), and up to `MODEL_TOP` unlinked decisions
at or above `MODEL_SHOW` are listed as model-inferred. A missing answer is reported as
"not checked", never as "no impact"; an inferred link is never a ratified relationship.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import docs, gitutil, s1
from .docs import Decision, glob_match, load_index
from .doctor import scan_code_refs
from .features import is_feature_map
from .gate import check
from .refs import find_refs

# eval/evidence (14 edits to real pillbox decisions x 24 others, Clef via Workers AI): links
# alone found 9 of 16 affected decisions; adding Clef's top 3 unlinked at p>=0.5 found 13 and
# added none for the 4 harmless edits. Chosen on those same cases: development evidence only.
MODEL_SHOW = 0.5
MODEL_TOP = 3
MAX_STATE_CHARS = 60_000  # as triage: past this the model judges truncated text

SECTIONS = ("What should change", "Why", "Code that needs it", "Impact / risk")
QUALIFIER_RE = re.compile(
    r"\b(never|always|only|unless|except|must not|must|may not|may|should|required|forbid\w*|"
    r"deny|denied|default|at most|at least|no more than|exactly|without|not)\b", re.IGNORECASE)
CLAIM_RE = re.compile(
    r"\b(tests? (?:pass|passed|passing|are green)|ci (?:is )?green|verified|benchmark\w*|"
    r"no (?:behaviou?r|functional) change|nothing else changes)\b", re.IGNORECASE)


@dataclass
class Line:
    line: int  # 1-based, in the file it came from
    text: str


@dataclass
class Link:
    doc_id: str
    title: str
    how: list[str]  # cites-it | cited-by-it | shared-files | model
    files: list[str] = field(default_factory=list)  # shared governed files (sample)
    p: float | None = None  # model: P(the edit undermines this decision); None = not asked/no answer


@dataclass
class Evidence:
    doc_id: str
    anchor_id: str
    ref: str
    path: str
    amendment_path: str
    removed: list[Line] = field(default_factory=list)  # baseline line numbers
    added: list[Line] = field(default_factory=list)  # proposed line numbers
    qualifiers_removed: list[str] = field(default_factory=list)
    qualifiers_added: list[str] = field(default_factory=list)
    frontmatter: list[str] = field(default_factory=list)  # `key: before -> after` per changed field
    sections: dict[str, Line] = field(default_factory=dict)  # heading -> its first body line
    claims: list[Line] = field(default_factory=list)  # amendment lines asserting unverified facts
    scope_before: list[str] = field(default_factory=list)
    scope_after: list[str] = field(default_factory=list)
    leaving: list[str] = field(default_factory=list)  # governed before, not after
    leaving_changed: list[str] = field(default_factory=list)  # ...and edited in this change
    code_refs: list[str] = field(default_factory=list)  # `file:line` sites citing the anchor
    links: list[Link] = field(default_factory=list)
    model: str = ""  # who answered, or why the shadow layer didn't run
    gaps: list[str] = field(default_factory=list)


def _qualifiers(lines: list[Line]) -> list[str]:
    return [m.group(1).lower() for ln in lines for m in QUALIFIER_RE.finditer(ln.text)]


def _minus(a: list[str], b: list[str]) -> list[str]:
    left = list(b)
    out = []
    for w in a:
        if w in left:
            left.remove(w)
        else:
            out.append(w)
    return sorted(set(out))


def _body_diff(before: docs.Anchor | None, after: docs.Anchor | None) -> tuple[list[Line], list[Line]]:
    """Lines removed from / added to one anchor's body, numbered in their own file."""
    old = before.body.splitlines() if before else []
    new = after.body.splitlines() if after else []
    o0 = before.start_line + 1 if before else 0
    n0 = after.start_line + 1 if after else 0
    removed, added = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += [Line(o0 + i, old[i]) for i in range(i1, i2) if old[i].strip()]
        if tag in ("replace", "insert"):
            added += [Line(n0 + j, new[j]) for j in range(j1, j2) if new[j].strip()]
    return removed, added


def _sections(text: str) -> tuple[dict[str, Line], list[Line]]:
    """Template sections (heading -> first non-empty body line) and unverified claims."""
    lines = text.splitlines()
    heads = [(i, ln.lstrip("#").strip()) for i, ln in enumerate(lines) if ln.startswith("## ")]
    found: dict[str, Line] = {}
    for n, (i, title) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = next(((j, lines[j]) for j in range(i + 1, end) if lines[j].strip()), None)
        name = next((s for s in SECTIONS if title.lower().startswith(s.lower().split(" /")[0])), title)
        if body and name not in found:
            found[name] = Line(body[0] + 1, body[1].strip())
    claims = [Line(i + 1, ln.strip()) for i, ln in enumerate(lines) if CLAIM_RE.search(ln)]
    return found, claims


def _governed(globs: list[str], files: list[str]) -> set[str]:
    return {f for f in files if any(glob_match(g, f) for g in globs)}


def _impact_state(edit: str, other: Decision) -> dict:
    return {"decision_edit": edit,
            "other_decision": "\n\n".join(f"{a.title}\n{a.body}" for a in other.anchors)}


def impact_question() -> dict:
    """noul over `_impact_state`: does the edit undermine the other decision? Shadow only."""
    return {
        "type": "noul",
        "instructions": (
            "The state holds an edit to one ratified engineering decision and the text of a second, "
            "different decision in the same repo. Does the edit undermine something the second decision "
            "states, relies on, or protects, so that the second decision should be revisited if the edit lands?"
        ),
        "criteria": {
            "true": "After the edit, the second decision's rule, rationale or invariant no longer holds as "
                    "written, or depends on something the edit removes or reverses.",
            "false": "The second decision is untouched by the edit: different subject, or the edit only "
                     "rewords, adds detail, or tightens without changing what the second decision relies on.",
        },
    }


def evidence(repo: Path, brief_dir: Path, base: str | None = None,
             via: s1.Client | None = None, model: bool = True) -> list[Evidence]:
    """Evidence for every pending amendment in the change (staged, or base..HEAD)."""
    repo, brief_dir = repo.resolve(), brief_dir.resolve()
    pend = [v for v in check(repo, brief_dir, base) if v.kind == "pending-ratification"]
    if not pend:
        return []
    baseline = gitutil.merge_base(repo, base) if base else "HEAD"
    rng = baseline if base else None
    index = [d for d in load_index(brief_dir) if not is_feature_map(d)]
    by_id = {d.doc_id: d for d in index}
    tracked = gitutil.tracked_files(repo)
    at_base = gitutil.files_at(repo, baseline, ".")  # a renamed-away file is only here
    changed = set(gitutil.changed_files(repo, rng))
    code_refs = scan_code_refs(repo, tracked)
    cites = {d.doc_id: {r.doc_id for r in find_refs(d.path.read_text(encoding="utf-8"))} - {d.doc_id}
             for d in index}
    client = (via or s1.client()) if model else None

    out = []
    for v in pend:
        d = by_id.get(v.doc_id)
        path = v.files[0] if v.files else ""
        amend_rel = (brief_dir / "amendments" / f"{v.anchor_id}.md").relative_to(repo).as_posix()
        ev = Evidence(v.doc_id, v.anchor_id, f"doc://{d.project if d else '?'}/{v.doc_id}@latest#{v.anchor_id}",
                      path, amend_rel)
        out.append(ev)
        if d is None:
            ev.gaps.append("decision not found in the working tree")
            continue
        try:
            before = docs.parse_text(gitutil.content_at(repo, path, baseline), Path(path), d.project)
        except docs.DocError as e:
            before = None
            ev.gaps.append(f"baseline decision unreadable: {e}")
        ev.removed, ev.added = _body_diff(before.anchor(v.anchor_id) if before else None, d.anchor(v.anchor_id))
        ev.qualifiers_removed = _minus(_qualifiers(ev.removed), _qualifiers(ev.added))
        ev.qualifiers_added = _minus(_qualifiers(ev.added), _qualifiers(ev.removed))
        if before:
            ev.frontmatter = [f"{k}: {before.meta.get(k)!r} -> {d.meta.get(k)!r}"
                              for k in sorted(before.meta.keys() | d.meta.keys(), key=str)
                              if before.meta.get(k) != d.meta.get(k)]
        if not ev.removed and not ev.added:
            ev.gaps.append("anchor text unchanged: the edit is frontmatter only" if ev.frontmatter
                           else "anchor text unchanged")

        text = gitutil.content_after(repo, amend_rel, rng)
        ev.sections, ev.claims = _sections(text)
        missing = [s for s in SECTIONS if s not in ev.sections]
        if not text.strip():
            ev.gaps.append("amendment file is empty")
        elif missing:
            ev.gaps.append("amendment lacks: " + ", ".join(missing))

        ev.scope_before = list(before.related_code) if before else []
        ev.scope_after = list(d.related_code)
        gov_before, gov_after = _governed(ev.scope_before, at_base), _governed(ev.scope_after, tracked)
        ev.leaving = sorted(gov_before - gov_after)
        ev.leaving_changed = sorted((gov_before - gov_after) & changed)
        ev.code_refs = [f"{c.file}:{c.line}" for c in code_refs
                        if c.ref.doc_id == d.doc_id and c.ref.anchor in (None, v.anchor_id)]

        governed = gov_before | gov_after
        links: dict[str, Link] = {}
        for o in index:
            if o.doc_id == d.doc_id:
                continue
            how = (["cites-it"] if d.doc_id in cites[o.doc_id] else []) + \
                  (["cited-by-it"] if o.doc_id in cites[d.doc_id] else [])
            shared = sorted(governed & _governed(o.related_code, tracked))
            if shared:
                how.append("shared-files")
            if how:
                links[o.doc_id] = Link(o.doc_id, o.anchors[0].title if o.anchors else o.doc_id, how, shared[:3])

        if not model:
            ev.model = "not run (--no-model)"
        elif client is None:
            ev.model = "not run: no System One model configured; inferred impacts were not checked"
        else:
            edit = gitutil.diff(repo, [path], rng)
            scores: dict[str, float | None] = {}
            answered_by: set[str] = set()
            for o in index:
                if o.doc_id == d.doc_id:
                    continue
                state = _impact_state(edit, o)
                if sum(len(x) for x in state.values()) > MAX_STATE_CHARS:
                    scores[o.doc_id] = None
                    continue
                a = s1.decide(state, {"undermines": impact_question()}, via=client)
                scores[o.doc_id] = s1.noul_p(a, "undermines")
                answered_by |= {x.model for x in (a or {}).values() if x.model}
            unanswered = sorted(k for k, p in scores.items() if p is None)
            ev.model = ",".join(sorted(answered_by)) or s1.model_name()
            if unanswered:
                ev.gaps.append(f"model gave no answer for {len(unanswered)} of {len(scores)} decisions "
                               f"(not checked, not cleared): {', '.join(unanswered[:5])}")
            for k, ln in links.items():
                ln.p = scores.get(k)
            extra = sorted(((p, k) for k, p in scores.items()
                            if p is not None and p >= MODEL_SHOW and k not in links), reverse=True)[:MODEL_TOP]
            for p, k in extra:
                o = by_id[k]
                links[k] = Link(k, o.anchors[0].title if o.anchors else k, ["model"], [], p)
        ev.links = sorted(links.values(), key=lambda ln: (-(ln.p or 0), "model" in ln.how, ln.doc_id))
    return out


def to_dict(evs: list[Evidence]) -> dict:
    return {"advisory": True, "amendments": [asdict(e) for e in evs]}


SHOW_LINES = 12  # per side in the markdown view; the JSON keeps every line


def _fmt(lines: list[Line], path: str, mark: str) -> list[str]:
    out = [f"  - `{path}:{ln.line}` {mark} {ln.text.strip()}" for ln in lines[:SHOW_LINES]]
    return out + ([f"  - … {len(lines) - SHOW_LINES} more {mark} lines (`--json` has all)"]
                  if len(lines) > SHOW_LINES else [])


def render_md(evs: list[Evidence]) -> str:
    if not evs:
        return "brief evidence: no pending amendments\n"
    L = ["# brief evidence (advisory: never read by the gate, triage or ratification)\n"]
    for e in evs:
        L.append(f"## `{e.doc_id}#{e.anchor_id}`\n")
        L.append(f"Decision: `{e.ref}` · amendment: `{e.amendment_path}`\n")
        if e.gaps:
            L.append("**Gaps (unknown, not safe):**")
            L += [f"- {g}" for g in e.gaps]
            L.append("")
        if e.removed or e.added:
            L.append("**Decision text changed**")
            L += _fmt(e.removed, e.path + "@base", "−") + _fmt(e.added, e.path, "+")
            if e.qualifiers_removed:
                L.append(f"- Qualifiers that left the text: {', '.join(f'`{q}`' for q in e.qualifiers_removed)}")
            if e.qualifiers_added:
                L.append(f"- Qualifiers that entered it: {', '.join(f'`{q}`' for q in e.qualifiers_added)}")
            L.append("")
        if e.frontmatter:
            L.append("**Frontmatter changed**")
            L += [f"- `{f}`" for f in e.frontmatter]
            L.append("")
        if e.sections:
            L.append("**The amendment says** (the author's words, not verified facts)")
            L += [f"- {k}: `{e.amendment_path}:{v.line}` {v.text}" for k, v in e.sections.items()]
            L += [f"- Unverified claim: `{e.amendment_path}:{c.line}` {c.text}" for c in e.claims]
            L.append("")
        if e.scope_before != e.scope_after or e.leaving:
            L.append("**Governed scope changed**")
            L.append(f"- before: {', '.join(f'`{g}`' for g in e.scope_before) or 'none'}")
            L.append(f"- after: {', '.join(f'`{g}`' for g in e.scope_after) or 'none'}")
            if e.leaving:
                L.append(f"- {len(e.leaving)} file(s) leave governance: "
                         + ", ".join(f"`{f}`" for f in e.leaving[:10]))
            if e.leaving_changed:
                L.append("- **edited in this change and leaving governance** (triage and sign-off no longer "
                         "see them): " + ", ".join(f"`{f}`" for f in e.leaving_changed))
            L.append("")
        if e.code_refs:
            L.append(f"**Code that cites this anchor** ({len(e.code_refs)}): "
                     + ", ".join(f"`{c}`" for c in e.code_refs[:10]))
            L.append("")
        L.append("**Other decisions to reconsider**")
        if not e.links:
            L.append("- none linked by refs or shared files")
        for ln in e.links:
            p = "" if ln.p is None else f" · model p={ln.p:.2f}"
            kind = "inferred by the model only" if ln.how == ["model"] else ", ".join(ln.how)
            files = f" ({', '.join(f'`{f}`' for f in ln.files)})" if ln.files else ""
            L.append(f"- `{ln.doc_id}`: {ln.title} · {kind}{files}{p}")
        L.append(f"- Model (shadow, advisory): {e.model}\n")
    return "\n".join(L)
