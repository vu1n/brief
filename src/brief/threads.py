"""Per-amendment PR threads: how a human ratifies or rejects one escalated amendment.

GitHub Actions has no reaction trigger, so the verdict is a reply command:

- `escalate` (CI, after triage says escalate): one review comment per escalated amendment,
  on line 1 of `.brief/amendments/<anchor>.md`, carrying `<!-- brief:amendment <anchor>
  <key> -->`; a revised amendment (new key) gets a reply in the same thread. Appends
  `<anchor> escalated: amendment=<key>` to .brief/RATIFICATIONS, which makes the gate block
  until a maintainer answers. Idempotent: nothing new means nothing posted or pushed.
- `command` (CI, on a comment starting `/ratify` or `/reject`): reply `/ratify` or
  `/reject <reason>` in the thread, or top-level `/ratify <anchor>` / `/reject <anchor>
  <reason>`. Refuses bots, comments carrying the Claude Code footer (an agent posting with
  its owner's token looks like the owner), users without write access, fork PRs, and an
  amendment that changed since the bot last showed it. Posts an attesting reply with
  `<!-- brief:recorded ... -->`, then commits the record line to the PR head.
- feedback: the escalation comment (and the automerge job's comment on a PR it merged)
  carries `<!-- brief:triage ... -->` and asks the owner for 👍/👎 on the call;
  `eval/amend/feedback.py` reads both back as labeled cases. Nothing in brief acts on them.
- `verify` (CI, govern job): every ratified-by/rejected-by line the PR adds must match an
  unedited attesting reply from github-actions[bot]. A commit's author is self-asserted; a
  bot comment is not.

Bot commits pushed with GITHUB_TOKEN start no workflow, so `escalate` and `command`
dispatch the brief workflow on the head branch to re-run the gate there.
Logic is pure and tested; `GH` is the only thing that talks to GitHub (the `gh` CLI).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from . import gitutil, verdicts
from .verdicts import bot_identity

FOOTER_RE = re.compile(r"generated (?:by|with) \[claude code\]", re.IGNORECASE)
MARKER_RE = re.compile(r"<!-- brief:amendment ([a-z0-9][a-z0-9-]*) ([0-9a-f]{12}) -->")
# One per bot comment that shows a triage call, so eval/amend/feedback.py can pair the
# owner's 👍 (the call was right) or 👎 (it was wrong) with the score that made it.
TRIAGE_RE = re.compile(r"<!-- brief:triage (escalated|automerged) ([a-z0-9][a-z0-9-]*) ([0-9a-f]{12}) "
                       r"p=(\S+) model=(\S*) -->")
RECORDED_RE = re.compile(
    r"<!-- brief:recorded ([a-z0-9][a-z0-9-]*) ([0-9a-f]{12}) (ratified|rejected) (\S+) (\d+) -->")
COMMAND_RE = re.compile(r"^\s*/(ratify|reject)(?=\s|$)(.*)", re.DOTALL)
ANCHOR_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
WRITE_ROLES = {"admin", "maintain", "write"}
WORKFLOW = "brief.yml"


class GHError(Exception):
    pass


class GH(Protocol):
    def api(self, path: str, method: str = "GET", body: dict | None = None) -> Any: ...


class CliGH:
    """`gh api`, authenticated by GH_TOKEN."""

    def api(self, path: str, method: str = "GET", body: dict | None = None) -> Any:
        args = ["gh", "api", "-X", method, path] + (["--input", "-"] if body is not None else [])
        r = subprocess.run(args, input=json.dumps(body) if body is not None else None,
                           capture_output=True, text=True, check=False)
        if r.returncode:
            raise GHError(f"{method} {path}: {(r.stdout + r.stderr).strip()}")
        return json.loads(r.stdout) if r.stdout.strip() else None


def paginate(gh: GH, path: str) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        batch = gh.api(f"{path}?per_page=100&page={page}") or []
        out += batch
        if len(batch) < 100:
            return out
        page += 1


# --- pure logic -------------------------------------------------------------------------

@dataclass
class Command:
    verb: str  # ratify | reject
    anchor: str | None
    reason: str


def _own_lines(body: str) -> list[str]:
    """The comment's own lines: quoted (`>`) lines and fenced code are someone else's text."""
    out, fenced = [], False
    for ln in (body or "").splitlines():
        if ln.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and not ln.lstrip().startswith(">"):
            out.append(ln)
    return out


def parse_command(body: str, in_thread: bool) -> Command | None:
    """`/ratify`, `/reject <reason>` in a thread; `/ratify <anchor>`, `/reject <anchor>
    <reason>` top-level. The command starts a line of the comment's own text, so a reply
    that quotes the bot's comment first still counts. None when there is no command."""
    lines = _own_lines(body)
    start = next((i for i, ln in enumerate(lines) if COMMAND_RE.match(ln)), None)
    m = COMMAND_RE.match("\n".join(lines[start:])) if start is not None else None
    if not m:
        return None
    rest = m[2].strip()
    anchor = None
    if not in_thread:
        anchor, _, rest = rest.partition(" ")
        rest = rest.strip()
        anchor = anchor.strip() or None
    return Command(m[1], anchor, verdicts.sanitize(rest))


def refusal(comment: dict, permission: dict | None) -> str | None:
    """Why this comment may not record a verdict, or None. `permission` is the
    collaborators/<user>/permission response (None if the lookup failed)."""
    user = comment.get("user") or {}
    if user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]"):
        return "bots can't ratify or reject"
    if FOOTER_RE.search(comment.get("body") or ""):
        return "this comment carries the Claude Code footer: an agent can't ratify or reject, even with its owner's token"
    roles = {(permission or {}).get("permission"), (permission or {}).get("role_name")}
    if not roles & WRITE_ROLES:
        return f"@{user.get('login')} needs write, maintain or admin access to this repository"
    return None


@dataclass
class Marker:
    comment_id: int
    root_id: int | None  # review thread root; None for a top-level PR comment
    anchor: str
    key: str


def _by_bot(c: dict) -> bool:
    u = c.get("user") or {}
    return u.get("login") == verdicts.BOT_LOGIN and u.get("type") == "Bot"


def markers(review_comments: list[dict], issue_comments: list[dict]) -> list[Marker]:
    """The bot's amendment markers, oldest first."""
    out = []
    for c, review in [(c, True) for c in review_comments] + [(c, False) for c in issue_comments]:
        if not _by_bot(c):
            continue
        for m in MARKER_RE.finditer(c.get("body") or ""):
            root = (c.get("in_reply_to_id") or c["id"]) if review else None
            out.append(Marker(c["id"], root, m[1], m[2]))
    return sorted(out, key=lambda m: m.comment_id)


def attested(review_comments: list[dict], issue_comments: list[dict]) -> set[tuple[str, ...]]:
    """(anchor, key, kind, login, comment id) of every verdict the bot recorded on this PR,
    from its unedited replies: anyone with write access can edit a bot's comment."""
    out = set()
    for c in review_comments + issue_comments:
        if _by_bot(c) and c.get("created_at") == c.get("updated_at"):
            out |= {m.groups() for m in RECORDED_RE.finditer(c.get("body") or "")}
    return out


def thread_body(a: dict, inline: bool = True, revised: bool = False) -> str:
    """The escalation comment for one amendment entry of `triage.verdict()`."""
    anchor, key = a["anchor_id"], a["key"]
    if a.get("review") is None:
        model = "No model opinion: a human decides."
    else:
        model = f"Model ({a.get('model') or 's1'}): p(needs the owner's eyes)={a['review']:.3f} — {a['why']}."
    head = "revised" if revised else "needs a maintainer's ratification"
    ratify, reject = ("`/ratify`", "`/reject <reason>`") if inline else (
        f"`/ratify {anchor}`", f"`/reject {anchor} <reason>`")
    where = "Reply in this thread" if inline else "Comment on this PR"
    p = "none" if a.get("review") is None else f"{a['review']:.4f}"
    return (
        f"<!-- brief:amendment {anchor} {key} -->\n"
        f"<!-- brief:triage escalated {anchor} {key} p={p} model={a.get('model') or ''} -->\n"
        f"**brief: amendment `{a['doc_id']}#{anchor}` {head}** (version `{key}`)\n\n"
        f"{model}\n\n"
        f"{where}:\n"
        f"- {ratify}: accept this version. Merging the PR then publishes it, stamped with your login.\n"
        f"- {reject}: send it back. The gate blocks the PR until the agent revises the amendment "
        f"(a new version comes back here) or withdraws it.\n\n"
        f"Agents: answer questions here, but you can't ratify or reject. A command from a bot, "
        f"or carrying the Claude Code footer, is refused; editing the amendment or the decision "
        f"text makes a new version that needs a new verdict.\n\n"
        f"Owner: once you've decided, react 👍 if this was worth your eyes or 👎 if it could have "
        f"merged on its own. `eval/amend/feedback.py` turns those into labeled cases for the cutoff."
    )


@dataclass
class Action:
    kind: str  # post | reply | record
    entry: dict
    root_id: int | None = None


def plan_escalation(amendments: list[dict], ms: list[Marker], records: list[verdicts.Record]) -> list[Action]:
    """What `escalate` does: a thread per escalated amendment that has none, a reply where
    the thread shows an older version, an `escalated` line for a version with no record."""
    acts = []
    for a in amendments:
        if a.get("auto"):
            continue
        mine = [m for m in ms if m.anchor == a["anchor_id"]]
        if not mine:
            acts.append(Action("post", a))
        elif a["key"] not in {m.key for m in mine}:
            acts.append(Action("reply", a, mine[0].root_id))
        if verdicts.state(records, a["anchor_id"], a["key"]) is None:
            acts.append(Action("record", a))
    return acts


# --- orchestration ----------------------------------------------------------------------

def _rel(repo: Path, p: Path) -> str:
    return p.resolve().relative_to(repo.resolve()).as_posix()


def _commit_and_push(repo: Path, brief_dir: Path, lines: list[str], message: str, branch: str) -> bool:
    log = brief_dir / verdicts.RECORDS
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    log.write_text(text + ("" if not text or text.endswith("\n") else "\n") + "".join(f"{ln}\n" for ln in lines),
                   encoding="utf-8")
    ident = {**os.environ, **bot_identity()}
    try:
        subprocess.run(["git", "-C", str(repo), "add", "--", _rel(repo, log)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", message, "--", _rel(repo, log)],
                       check=True, capture_output=True, env=ident)
        subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", f"HEAD:refs/heads/{branch}"],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError:
        return False
    return True


def _dispatch(gh: GH, name: str, pr: dict) -> None:
    gh.api(f"repos/{name}/actions/workflows/{WORKFLOW}/dispatches", "POST",
           {"ref": pr["head"]["ref"], "inputs": {"pr": str(pr["number"]), "base": pr["base"]["ref"]}})


def _same_repo(pr: dict) -> bool:
    return (pr["head"].get("repo") or {}).get("full_name") == pr["base"]["repo"]["full_name"]


def _comments(gh: GH, name: str, n: int) -> tuple[list[dict], list[dict]]:
    return paginate(gh, f"repos/{name}/pulls/{n}/comments"), paginate(gh, f"repos/{name}/issues/{n}/comments")


def _records(brief_dir: Path) -> list[verdicts.Record]:
    log = brief_dir / verdicts.RECORDS
    return verdicts.parse(log.read_text(encoding="utf-8")) if log.exists() else []


def escalate(gh: GH, name: str, n: int, triage: dict, repo: Path, brief_dir: Path) -> list[str]:
    """Run `plan_escalation` against the PR. The working tree must be the PR head."""
    pr = gh.api(f"repos/{name}/pulls/{n}")
    if not _same_repo(pr):
        return ["fork PR: no threads or records (the token can't write); a maintainer's merge ratifies"]
    rc, ic = _comments(gh, name, n)
    done, records = [], []
    for act in plan_escalation(triage.get("amendments", []), markers(rc, ic), _records(brief_dir)):
        a = act.entry
        if act.kind == "record":
            records.append(verdicts.Record(a["anchor_id"], "escalated", a["key"]).line())
        elif act.kind == "reply" and act.root_id is not None:
            gh.api(f"repos/{name}/pulls/{n}/comments/{act.root_id}/replies", "POST",
                   {"body": thread_body(a, revised=True)})
            done.append(f"replied: {a['anchor_id']} revised ({a['key']})")
        elif act.kind == "reply":
            gh.api(f"repos/{name}/issues/{n}/comments", "POST", {"body": thread_body(a, inline=False, revised=True)})
            done.append(f"commented: {a['anchor_id']} revised ({a['key']})")
        else:
            path = _rel(repo, brief_dir / "amendments" / f"{a['anchor_id']}.md")
            try:
                gh.api(f"repos/{name}/pulls/{n}/comments", "POST",
                       {"body": thread_body(a), "commit_id": pr["head"]["sha"], "path": path,
                        "line": 1, "side": "RIGHT"})
            except GHError:  # the amendment file isn't in the PR's diff: top-level instead
                gh.api(f"repos/{name}/issues/{n}/comments", "POST", {"body": thread_body(a, inline=False)})
            done.append(f"opened thread: {a['anchor_id']} ({a['key']})")
    if records:
        if _commit_and_push(repo, brief_dir, records, "brief: escalate amendments", pr["head"]["ref"]):
            _dispatch(gh, name, pr)
            done += [f"recorded: {r}" for r in records]
        else:
            done.append("branch moved: records not pushed (the newer push re-runs escalation)")
    return done


def command(gh: GH, name: str, event: dict, repo: Path, brief_dir: Path) -> str:
    """Handle one `/ratify` or `/reject` comment event. Returns what it replied."""
    c = event["comment"]
    in_thread = "pull_request" in event
    if not in_thread and "pull_request" not in (event.get("issue") or {}):
        return "not a PR comment"
    n = event["pull_request"]["number"] if in_thread else event["issue"]["number"]
    cmd = parse_command(c.get("body") or "", in_thread)
    if cmd is None:
        return "not a command"
    root = c.get("in_reply_to_id") or c["id"]

    def reply(text: str) -> str:
        if in_thread:
            gh.api(f"repos/{name}/pulls/{n}/comments/{root}/replies", "POST", {"body": text})
        else:
            gh.api(f"repos/{name}/issues/{n}/comments", "POST", {"body": text})
        return text

    login = (c.get("user") or {}).get("login", "")
    try:
        perm = gh.api(f"repos/{name}/collaborators/{login}/permission")
    except GHError:
        perm = None
    if why := refusal(c, perm):
        return reply(f"brief: not recorded — {why}.")
    pr = gh.api(f"repos/{name}/pulls/{n}")
    if not _same_repo(pr):
        return reply("brief: not recorded — this PR is from a fork, so CI can't commit the verdict to it. "
                     "A maintainer's merge ratifies it.")
    ms = markers(*_comments(gh, name, n))
    if in_thread:
        anchor = next((m.anchor for m in ms if m.root_id == root), None)
        if anchor is None:
            return reply("brief: not recorded — this is not a brief amendment thread. "
                         "Reply in the amendment's thread, or comment `/ratify <anchor>` on the PR.")
    else:
        anchor = cmd.anchor
        if not anchor or not ANCHOR_RE.match(anchor):
            return reply(f"brief: not recorded — say which amendment: `/{cmd.verb} <anchor>`.")
    shown = [m for m in ms if m.anchor == anchor]
    if not shown:
        return reply(f"brief: not recorded — no escalated amendment `{anchor}` on this PR.")
    if cmd.verb == "reject" and not cmd.reason:
        return reply("brief: not recorded — give a reason: the agent revises from it.")
    key = verdicts.key_in_tree(brief_dir, anchor)
    if key is None:
        return reply(f"brief: not recorded — the PR head has no `.brief/amendments/{anchor}.md` (withdrawn?).")
    if key != shown[-1].key:
        return reply(f"brief: not recorded — the amendment changed since this thread showed version "
                     f"`{shown[-1].key}` (the head is `{key}`). Wait for the bot's update and read it again.")
    kind = "ratified" if cmd.verb == "ratify" else "rejected"
    rec = verdicts.Record(anchor, kind, key, login, str(c["id"]), c.get("html_url", ""), cmd.reason)
    after = ("Merging the PR publishes it." if kind == "ratified" else
             "The gate blocks the PR until the agent revises the amendment (a new version comes back "
             "here) or withdraws it.")
    reply(f"<!-- brief:recorded {anchor} {key} {kind} {login} {c['id']} -->\n"
          f"brief: recorded — `{anchor}` version `{key}` {kind} by @{login}. {after}")
    if not _commit_and_push(repo, brief_dir, [rec.line()], f"brief: {anchor} {kind} by {login}", pr["head"]["ref"]):
        return reply("brief: the record could not be pushed (the branch moved). Post the command again.")
    _dispatch(gh, name, pr)
    return f"recorded {rec.line()}"


def verify(gh: GH, name: str, n: int, repo: Path, brief_dir: Path, base: str) -> list[str]:
    """Ratified-by/rejected-by lines this PR adds that no unedited bot reply attests."""
    rel = _rel(repo, brief_dir / verdicts.RECORDS)
    rng = gitutil.merge_base(repo, base)
    on_base = set(gitutil.content_at(repo, rel, base).splitlines())
    need = [r for ln in verdicts.provenance(repo, rel, base, rng).added
            if ln not in on_base and (r := verdicts.parse_line(ln)) and r.kind != "escalated"]
    if not need:
        return []
    ok = attested(*_comments(gh, name, n))
    return [r.line() for r in need if (r.anchor, r.key, r.kind, r.who, r.comment) not in ok]
