"""Turn the owner's 👍/👎 on brief's triage comments into labeled cases for `eval/cutoff.py`.

Every triage call brief shows a person carries `<!-- brief:triage <kind> <anchor> <key> p=<p>
model=<m> -->` (`threads.TRIAGE_RE`): the escalation thread for an amendment it held back,
and the comment CI's automerge job leaves on a PR it merged. A reaction grades the call, so
👍 always means the bot got it right:

| comment | 👍 | 👎 |
|---|---|---|
| escalated | worth the owner's eyes (should see) | could have merged on its own (harmless) |
| automerged | fine to merge (harmless) | should have been shown first (should see: a miss) |

Only reactions from people with write access count. A comment with both a 👍 and a 👎 from
graders is a disagreement and is left out. The rows are written per model, in the shape
`eval/amend/run.py` saves, so the cutoff re-tunes on real calls:

    GH_TOKEN=... python eval/amend/feedback.py vu1n/pillbox vu1n/kypp
    python eval/cutoff.py --pool eval/amend/results/clef.jsonl eval/amend/results/feedback/clef.jsonl

Unlike `cases.jsonl.gz`, these cases saw the governed code change too, as CI's triage does.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "src"))
from brief.threads import TRIAGE_RE, WRITE_ROLES, CliGH, paginate, _by_bot  # noqa: E402

# (kind, reaction) -> should the owner see it?
LABEL = {("escalated", "+1"): True, ("escalated", "-1"): False,
         ("automerged", "+1"): False, ("automerged", "-1"): True}


def label(kind: str, reactions: list[dict], graders: set[str]) -> tuple[bool | None, str]:
    """(should_see, who) from a comment's reactions; None when nobody graded it or they disagree."""
    votes = {(r["content"], r["user"]["login"]) for r in reactions
             if r.get("content") in ("+1", "-1") and (r.get("user") or {}).get("login") in graders}
    seen = {LABEL[kind, c] for c, _ in votes}
    if len(seen) != 1:
        return None, ""
    return seen.pop(), ",".join(sorted(f"{who}:{c}" for c, who in votes))


def rows(comment: dict, repo: str, should_see: bool, who: str) -> list[dict]:
    """One row per marker. A 👎 on an automerge comment that names several amendments doesn't
    say which one needed eyes, so it labels none of them (a 👍 clears them all)."""
    url = comment.get("pull_request_url") or comment.get("issue_url") or ""
    pr = url.rsplit("/", 1)[-1]
    found = TRIAGE_RE.findall(comment.get("body") or "")
    if should_see and len(found) > 1:
        return []
    out = []
    for kind, anchor, key, p, model in found:
        out.append({"id": f"{repo}#{pr}/{anchor}/{key}", "source": "feedback", "category": kind,
                    "escalate": should_see, "review": None if p == "none" else float(p),
                    "model": model, "note": who})
    return out


def collect(gh, repo: str) -> list[dict]:
    perms: dict[str, bool] = {}

    def grader(login: str) -> bool:
        if login not in perms:
            try:
                perm = gh.api(f"repos/{repo}/collaborators/{login}/permission") or {}
            except Exception:  # not a collaborator
                perm = {}
            perms[login] = perm.get("permission") in WRITE_ROLES or perm.get("role_name") in WRITE_ROLES
        return perms[login]

    out = []
    for kind, path in (("pulls", f"repos/{repo}/pulls/comments"), ("issues", f"repos/{repo}/issues/comments")):
        for c in paginate(gh, path):
            if not _by_bot(c) or not TRIAGE_RE.search(c.get("body") or ""):
                continue
            counts = c.get("reactions") or {}
            if not (counts.get("+1") or counts.get("-1")):
                continue
            reactions = paginate(gh, f"repos/{repo}/{kind}/comments/{c['id']}/reactions")
            graders = {r["user"]["login"] for r in reactions
                       if (r.get("user") or {}).get("type") != "Bot" and grader(r["user"]["login"])}
            kinds = {m[0] for m in TRIAGE_RE.findall(c["body"])}
            should_see, who = label(kinds.pop(), reactions, graders) if len(kinds) == 1 else (None, "")
            if should_see is not None:
                out += rows(c, repo, should_see, who)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repos", nargs="+", help="owner/name of each repo brief governs")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "feedback")
    a = ap.parse_args()
    gh = CliGH()
    found = [r for repo in a.repos for r in collect(gh, repo)]
    by_model: dict[str, list[dict]] = {}
    for r in found:
        by_model.setdefault(r["model"] or "unknown", []).append(r)
    a.out.mkdir(parents=True, exist_ok=True)
    for old in a.out.glob("*.jsonl"):  # a snapshot of the current grades, never a log
        old.unlink()
    for model, rs in by_model.items():
        path = a.out / f"{model.replace('/', '_')}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rs))
        bad = sum(r["escalate"] for r in rs)
        print(f"{path}: {len(rs)} graded calls ({bad} should see, {len(rs) - bad} harmless)")
    if not found:
        print("no graded triage calls yet: react 👍/👎 on brief's escalation and automerge comments")


if __name__ == "__main__":
    main()
