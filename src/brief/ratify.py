"""Ratify — the authorized path to change a locked decision (the L3 mechanical bit).

Default workflow: the amendment PR carries `.brief/amendments/<anchor>.md` and the
proposed decision text (the gate reports it as pending-ratification), a human reviews and
merges it, and the CI job `brief init --ci` writes runs `ratify_pending` on the default
branch, which publishes the revision and archives the amendment as ratified by the merger.
An amendment CI escalated is published only once a maintainer `/ratify`d it in its PR
thread (`verdicts`, `threads`). When the triage rated every amendment auto-ratifiable, CI
merges the PR itself and records the model as the ratifier (`ratify_pending(model=...)`,
`ratified_via: model`). By hand, a human edits the live decision and runs `brief ratify <anchor>`.

Authority is the human (or, for an auto-ratifiable PR, the model) merging the PR / running
it — `brief` makes ratification an explicit, structured, reviewable act. The gate exempts the decision edit only when the
change carries this function's full output: the new archived amendment (stamped
`ratified_rev`) and the new published revision equal to the live doc (see
`gate._ratified`). A bare file in the archive is not enough. It still cannot locally
prevent a hand-forged copy of that output; CI + human PR review is the backstop.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import verdicts, versions
from .docs import load_index, parse_doc


# `ratified_via:` in the archive: who held the authority. A model ratification (CI merged the
# PR on an all-auto-ratifiable triage) is weaker than a person's, and consumers (e.g. kypp's
# sync) read it to rank the revision below a human one.
HUMAN, MODEL = "human", "model"


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


def _archive(brief_dir: Path, doc_id: str, anchor_id: str, rev: int, by: str | None,
             via: str = HUMAN) -> Ratification:
    proposal = brief_dir / "amendments" / f"{anchor_id}.md"
    archive = brief_dir / "amendments" / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    dest = archive / f"{anchor_id}-v{rev:04d}.md"
    dest.write_text(
        proposal.read_text(encoding="utf-8")
        + f"\n\n---\nratified_rev: {rev:04d}\nratified_by: {by or 'unknown'}\nratified_via: {via}\n",
        encoding="utf-8",
    )
    proposal.unlink()
    return Ratification(doc_id=doc_id, anchor=anchor_id, rev=rev, archived=str(dest))


def ratify_pending(brief_dir: Path, by: str | None = None, held: list[str] | None = None,
                   model: dict | None = None) -> list[Ratification]:
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
    if model is not None and model.get("verdict") != "auto-ratifiable":
        raise RatifyError(f"the triage verdict is {model.get('verdict')!r}, not auto-ratifiable: a model can't ratify it")
    if model is not None and not (model.get("stamp") and (by or "").startswith(model["stamp"])):
        raise RatifyError(f"a model ratification is stamped with the triage's stamp: --by must start with {model.get('stamp')!r}")
    cleared = {(a["anchor_id"], a["key"]) for a in (model or {}).get("amendments", []) if a.get("auto")}
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
        stamps: dict[str, tuple[str | None, str]] = {}
        blocked = []
        for a in props:
            anchor = d.anchor(a)
            text = (brief_dir / "amendments" / f"{a}.md").read_text(encoding="utf-8")
            key = verdicts.amendment_key(text, anchor.hash if anchor else "")
            r = verdicts.state(records, a, key)
            if r is not None and r.kind != "ratified":
                blocked.append(f"{d.doc_id}#{a}: {r.kind}")
            elif r is not None:
                stamps[a] = (f"{r.who} via /ratify ({r.url}); {by or 'unknown'}", HUMAN)
            elif model is None:
                stamps[a] = (by, HUMAN)  # the merger ratified it
            elif (a, key) in cleared:
                stamps[a] = (by, MODEL)
            else:
                blocked.append(f"{d.doc_id}#{a}: not cleared by the model (version {key})")
        if blocked:
            if held is not None:
                held += blocked
            continue  # one unanswered, rejected or uncleared anchor holds the whole doc
        rev = versions.publish(brief_dir, d.doc_id)
        out += [_archive(brief_dir, d.doc_id, a, rev, *stamps[a]) for a in props]
    return out


def ratify_and_push(repo: Path, brief_dir: Path, by: str | None, model: dict | None = None,
                    attempts: int = 3) -> tuple[list[Ratification], list[str]]:
    """CI, on the default branch's tip after a merge: `ratify_pending`, commit `.brief` as
    github-actions[bot] and push. If the branch moved meanwhile, reset to its new tip and
    redo, rather than leave the merge unrecorded for the next push to stamp with the wrong
    ratifier. Returns (ratified, held); nothing to ratify commits nothing."""
    def git(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              check=False, env=env)

    branch = git("symbolic-ref", "--short", "HEAD").stdout.strip()
    if not branch:
        raise RatifyError("ratify --push needs a checked-out branch (the default branch's tip)")
    rel = brief_dir.resolve().relative_to(repo.resolve()).as_posix()
    for _ in range(attempts):
        held: list[str] = []
        done = ratify_pending(brief_dir, by, held, model)
        if not git("status", "--porcelain", "--", rel).stdout.strip():
            return done, held
        git("add", "--", rel)
        c = git("commit", "-qm", f"brief: ratify amendments ({by or 'unknown'})", "--", rel,
                env={**os.environ, **verdicts.bot_identity()})
        if c.returncode:
            raise RatifyError(f"commit failed: {(c.stdout + c.stderr).strip()}")
        if not git("push", "-q", "origin", f"HEAD:refs/heads/{branch}").returncode:
            return done, held
        if git("fetch", "-q", "origin", branch).returncode or git("reset", "-q", "--hard", "FETCH_HEAD").returncode:
            break
    raise RatifyError(f"could not push the ratification to {branch}: run `brief ratify --pending` by hand")
