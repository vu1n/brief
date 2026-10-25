"""Per-amendment PR threads: an escalated amendment gets a thread, a maintainer answers it
with /ratify or /reject, CI records the verdict in .brief/RATIFICATIONS, the gate blocks a
rejected or unanswered one, and `ratify --pending` publishes only what was ratified. Only the
bot writes the log: a forged line is untrusted, and in CI a verdict must match the bot's reply."""
import os
import subprocess

import yaml

from brief import verdicts, versions
from brief.docs import load_index
from brief.gate import check
from brief.ratify import ratify_pending
from brief.templates import CI_WORKFLOW
from brief.threads import (
    TRIAGE_RE,
    GHError,
    Marker,
    attested,
    bot_identity,
    command,
    escalate,
    markers,
    parse_command,
    plan_escalation,
    refusal,
    thread_body,
    verify,
)
from tests.test_amend_merge import ANCHOR, _amend_pr
from tests.test_thin import _git, write

BOT = {"login": "github-actions[bot]", "type": "Bot"}
VU = {"login": "vu1n", "type": "User"}
DOC = "ADR-001-backend"


def _bot_commit(repo, *lines, extra=None):
    log = repo / ".brief" / verdicts.RECORDS
    log.write_text((log.read_text() if log.exists() else "") + "".join(f"{ln}\n" for ln in lines))
    if extra:
        write(repo / extra, "x\n")
    _git(repo, "add", "-A")
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "brief: record"], check=True,
                   capture_output=True, env={**os.environ, **bot_identity()})


def _rec(kind, key, who="vu1n", reason="too broad"):
    return verdicts.Record(ANCHOR, kind, key, "" if kind == "escalated" else who,
                           "" if kind == "escalated" else "11", "" if kind == "escalated" else "https://x/11",
                           reason if kind == "rejected" else "")


def _state(repo, bd, base):
    return {(v.kind, v.blocking) for v in check(repo, bd, base=base)}


# --- the record -----------------------------------------------------------------------

def test_record_lines_roundtrip_and_reject_junk():
    for r in (_rec("escalated", "a" * 12), _rec("ratified", "b" * 12), _rec("rejected", "c" * 12)):
        assert verdicts.parse_line(r.line()) == r
    assert verdicts.parse_line(f"{ANCHOR} ratified-by: vu1n amendment={'a' * 12}") is None  # no comment
    assert verdicts.parse_line("x conforms: whatever") is None
    assert verdicts.sanitize("a\nb   c") == "a b c"


def test_key_moves_with_amendment_or_decision_text():
    k = verdicts.amendment_key("amend", "sha256:1")
    assert k != verdicts.amendment_key("amend v2", "sha256:1") != verdicts.amendment_key("amend", "sha256:2")


def test_state_is_the_latest_verdict_for_this_version():
    recs = [_rec("escalated", "a" * 12), _rec("rejected", "a" * 12), _rec("ratified", "a" * 12)]
    assert verdicts.state(recs, ANCHOR, "a" * 12).kind == "ratified"
    assert verdicts.state(recs[:2], ANCHOR, "a" * 12).kind == "rejected"
    assert verdicts.state(recs[:1], ANCHOR, "a" * 12).kind == "escalated"
    assert verdicts.state(recs, ANCHOR, "b" * 12) is None  # a revision starts over


# --- the gate -------------------------------------------------------------------------

def test_escalated_blocks_until_ratified(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    key = verdicts.key_in_tree(bd, ANCHOR)
    assert _state(repo, bd, base) == {("pending-ratification", False)}
    _bot_commit(repo, _rec("escalated", key).line())
    [v] = check(repo, bd, base=base)
    assert v.kind == "pending-ratification" and v.blocking and "/ratify" in v.detail
    _bot_commit(repo, _rec("ratified", key).line())
    [v] = check(repo, bd, base=base)
    assert not v.blocking and "ratified by vu1n" in v.detail


def test_rejected_blocks_and_a_revision_reescalates(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    key = verdicts.key_in_tree(bd, ANCHOR)
    _bot_commit(repo, _rec("escalated", key).line(), _rec("rejected", key).line())
    [v] = check(repo, bd, base=base)
    assert (v.kind, v.blocking) == ("amendment-rejected", True) and "too broad" in v.detail
    r = subprocess.run(["brief", "check", "--repo", str(repo), "--base", base], capture_output=True, text=True)
    assert r.returncode == 1 and "revise" in r.stderr and "never edit .brief/RATIFICATIONS" in r.stderr
    # the agent revises the amendment: a new version, no verdict yet (CI escalates it again)
    (bd / "amendments" / f"{ANCHOR}.md").write_text("# Amendment\nadmit docker only for one customer\n")
    _git(repo, "commit", "-qam", "revise")
    assert _state(repo, bd, base) == {("pending-ratification", False)}


def test_forged_ratified_line_is_untrusted(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    key = verdicts.key_in_tree(bd, ANCHOR)
    _bot_commit(repo, _rec("escalated", key).line())
    write(bd / verdicts.RECORDS, (bd / verdicts.RECORDS).read_text() + _rec("ratified", key).line() + "\n")
    _git(repo, "commit", "-qam", "ratify myself")  # the agent's identity
    v = check(repo, bd, base=base)
    assert ("untrusted-verdict", True) in {(x.kind, x.blocking) for x in v}
    # the forged line doesn't count either: the amendment is still waiting
    assert any(x.kind == "pending-ratification" and x.blocking for x in v)


def test_bot_identity_on_a_mixed_commit_is_untrusted(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    key = verdicts.key_in_tree(bd, ANCHOR)
    _bot_commit(repo, _rec("ratified", key).line(), extra="src/sandbox/mod.rs")
    assert "untrusted-verdict" in {x.kind for x in check(repo, bd, base=base)}


def test_removing_a_line_is_untrusted(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    key = verdicts.key_in_tree(bd, ANCHOR)
    _bot_commit(repo, _rec("escalated", key).line(), _rec("rejected", key).line())
    _git(repo, "push", "-q", ".", "HEAD:refs/heads/main-tip")  # stand-in for a base that has the lines
    (bd / verdicts.RECORDS).write_text(_rec("escalated", key).line() + "\n")
    _git(repo, "commit", "-qam", "drop the rejection")
    v = check(repo, bd, base="main-tip")
    assert any(x.kind == "untrusted-verdict" and "removed" in x.detail for x in v)


def test_staged_edit_of_the_log_is_untrusted(tmp_path):
    repo, bd, _ = _amend_pr(tmp_path)
    write(bd / verdicts.RECORDS, _rec("ratified", "a" * 12).line() + "\n")
    _git(repo, "add", "-A")
    assert "untrusted-verdict" in {x.kind for x in check(repo, bd)}


# --- ratify --pending at merge ------------------------------------------------------------

def test_ratify_pending_publishes_ratified_and_stamps_the_maintainer(tmp_path):
    repo, bd, _ = _amend_pr(tmp_path)
    key = verdicts.key_in_tree(bd, ANCHOR)
    write(bd / verdicts.RECORDS, _rec("escalated", key).line() + "\n" + _rec("ratified", key).line() + "\n")
    [r] = ratify_pending(bd, by="vu1n (merge of #7)")
    assert "ratified_by: vu1n via /ratify (https://x/11); vu1n (merge of #7)" in open(r.archived).read()


def test_ratify_pending_holds_unanswered_or_rejected(tmp_path):
    repo, bd, _ = _amend_pr(tmp_path)
    key = verdicts.key_in_tree(bd, ANCHOR)
    for lines in ([_rec("escalated", key)], [_rec("escalated", key), _rec("rejected", key)]):
        write(bd / verdicts.RECORDS, "".join(r.line() + "\n" for r in lines))
        held = []
        assert ratify_pending(bd, by="x", held=held) == []
        assert held == [f"{DOC}#{ANCHOR}: {lines[-1].kind}"]
        assert versions.latest_rev(bd, DOC) == 1
    # a ratification of an older version doesn't cover this one
    write(bd / verdicts.RECORDS, _rec("escalated", key).line() + "\n" + _rec("ratified", "f" * 12).line() + "\n")
    assert ratify_pending(bd, by="x") == []


def test_ratify_pending_mixed_doc_publishes_only_when_every_anchor_is_cleared(tmp_path):
    repo, bd, _ = _amend_pr(tmp_path)
    live = versions.live_doc(bd, DOC)
    live.write_text(live.read_text() + "\n<!-- brief:anchor docker-flag -->\n## Docker flag\nOff by default.\n")
    write(bd / "amendments" / "docker-flag.md", "# Amendment\nadd the flag\n")
    key = verdicts.key_in_tree(bd, ANCHOR)
    other = verdicts.Record("docker-flag", "escalated", verdicts.key_in_tree(bd, "docker-flag"))
    write(bd / verdicts.RECORDS, "".join(r.line() + "\n" for r in (_rec("ratified", key), other)))
    held = []
    assert ratify_pending(bd, by="x", held=held) == [] and held == [f"{DOC}#docker-flag: escalated"]
    # the other anchor was never escalated (the model cleared it): the merge ratifies it
    write(bd / verdicts.RECORDS, _rec("ratified", key).line() + "\n")
    done = ratify_pending(bd, by="x")
    assert sorted(r.anchor for r in done) == sorted([ANCHOR, "docker-flag"])


# --- threads: pure logic ----------------------------------------------------------------

def test_parse_command():
    assert parse_command("/ratify", True).verb == "ratify"
    c = parse_command("/reject  widens\nthe sandbox ", True)
    assert (c.verb, c.anchor, c.reason) == ("reject", None, "widens the sandbox")
    c = parse_command(f"/reject {ANCHOR} too broad", False)
    assert (c.anchor, c.reason) == (ANCHOR, "too broad")
    assert parse_command(f"/ratify {ANCHOR}", False).anchor == ANCHOR
    for body in ("/ratifyx", "please /ratify", "", "LGTM"):
        assert parse_command(body, True) is None


def test_parse_command_below_a_quote():
    # GitHub's "Quote reply" puts the bot's comment, with its own `/ratify` lines, first
    quoted = f"> **brief: amendment needs a maintainer's ratification**\n>\n> * `/ratify {ANCHOR}`\n\n"
    assert parse_command(quoted + f"/ratify {ANCHOR}", False).anchor == ANCHOR
    c = parse_command(quoted + f"/reject {ANCHOR} too broad\nand untested", False)
    assert (c.verb, c.reason) == ("reject", "too broad and untested")
    for body in (quoted, f"> /ratify {ANCHOR}", f"```\n/ratify {ANCHOR}\n```", "comment `/ratify x` to ratify",
                 f"~~~\n/ratify {ANCHOR}\n~~~", f"````\n```\n/ratify {ANCHOR}\n```\n````",
                 f"```\n~~~\n/ratify {ANCHOR}\n```", f"Example:\n\n    /ratify {ANCHOR}", f"\t/ratify {ANCHOR}",
                 f"> Example only:\n/ratify {ANCHOR}"):  # a lazy continuation is still the quote
        assert parse_command(body, False) is None, body
    assert parse_command(f"```\nexample\n```\n/ratify {ANCHOR}", False).anchor == ANCHOR


def test_refusal_rules():
    ok = {"permission": "write", "role_name": "write"}
    assert refusal({"user": VU, "body": "/ratify"}, ok) is None
    assert refusal({"user": VU, "body": "/ratify"}, {"permission": "write", "role_name": "maintain"}) is None
    assert "bots" in refusal({"user": BOT, "body": "/ratify"}, ok)
    assert "bots" in refusal({"user": {"login": "renovate[bot]", "type": "User"}, "body": "/ratify"}, ok)
    footer = "/ratify\n\n🤖 Generated by [Claude Code](https://claude.com/claude-code)"
    assert "footer" in refusal({"user": VU, "body": footer}, ok)
    assert "write" in refusal({"user": VU, "body": "/ratify"}, {"permission": "read", "role_name": "triage"})
    assert "write" in refusal({"user": VU, "body": "/ratify"}, None)


def _entry(key="a" * 12, auto=False, review=0.4):
    return {"doc_id": DOC, "anchor_id": ANCHOR, "review": review, "model": "clef",
            "auto": auto, "why": "the owner should see it", "key": key}


def test_thread_body_carries_marker_scores_and_commands():
    b = thread_body(_entry())
    assert b.startswith(f"<!-- brief:amendment {ANCHOR} {'a' * 12} -->")
    assert "p(needs the owner's eyes)=0.400" in b and "`/ratify`" in b and "`/reject <reason>`" in b
    assert "No model opinion" in thread_body(_entry(review=None))
    [m] = TRIAGE_RE.finditer(b)  # what eval/amend/feedback.py pairs with the owner's reaction
    assert m.groups() == ("escalated", ANCHOR, "a" * 12, "0.4000", "clef") and "react 👍" in b
    assert TRIAGE_RE.search(thread_body(_entry(review=None)))[4] == "none"
    top = thread_body(_entry(), inline=False)
    assert f"`/ratify {ANCHOR}`" in top and f"`/reject {ANCHOR} <reason>`" in top
    assert "revised" in thread_body(_entry(), revised=True)


def test_markers_and_attestations_trust_only_the_bot():
    body = thread_body(_entry())
    rc = [{"id": 5, "user": BOT, "body": body},
          {"id": 6, "user": VU, "body": thread_body(_entry("b" * 12))},  # a human pasting a marker
          {"id": 7, "user": BOT, "in_reply_to_id": 5, "body": thread_body(_entry("c" * 12), revised=True)}]
    assert markers(rc, []) == [Marker(5, 5, ANCHOR, "a" * 12), Marker(7, 5, ANCHOR, "c" * 12)]
    rec = f"<!-- brief:recorded {ANCHOR} {'a' * 12} ratified vu1n 9 -->"
    seen = attested([{"id": 8, "user": BOT, "body": rec, "created_at": "t", "updated_at": "t"}], [])
    assert seen == {(ANCHOR, "a" * 12, "ratified", "vu1n", "9")}
    assert attested([{"id": 8, "user": BOT, "body": rec, "created_at": "t", "updated_at": "t2"}], []) == set()
    assert attested([], [{"id": 8, "user": VU, "body": rec, "created_at": "t", "updated_at": "t"}]) == set()


def test_plan_escalation_is_idempotent():
    k = "a" * 12
    assert [a.kind for a in plan_escalation([_entry(k)], [], [])] == ["post", "record"]
    assert plan_escalation([_entry(k)], [Marker(5, 5, ANCHOR, k)], [_rec("escalated", k)]) == []
    assert plan_escalation([_entry(k, auto=True)], [], []) == []
    # decided already: no new escalated line
    assert plan_escalation([_entry(k)], [Marker(5, 5, ANCHOR, k)], [_rec("rejected", k)]) == []
    revised = plan_escalation([_entry("b" * 12)], [Marker(5, 5, ANCHOR, k)], [_rec("rejected", k)])
    assert [(a.kind, a.root_id) for a in revised] == [("reply", 5), ("record", None)]


# --- threads: against a fake GitHub --------------------------------------------------------

class FakeGH:
    def __init__(self, n=7, perm="write", inline_ok=True):
        self.n, self.perm, self.inline_ok = n, perm, inline_ok
        self.review, self.issue, self.dispatched, self.next = [], [], [], 100
        self.pr = {"number": n, "head": {"ref": "feature", "sha": "abc", "repo": {"full_name": "o/r"}},
                   "base": {"ref": "main", "repo": {"full_name": "o/r"}}}

    def api(self, path, method="GET", body=None):
        p = path.split("?")[0]
        if method == "GET":
            if p == f"repos/o/r/pulls/{self.n}":
                return self.pr
            if p.endswith("/comments"):
                src = self.review if "/pulls/" in p else self.issue
                return list(src) if "page=1" in path else []
            if "/collaborators/" in p:
                if self.perm is None:
                    raise GHError("404")
                return {"permission": self.perm, "role_name": self.perm}
        if p.endswith("/dispatches"):
            self.dispatched.append(body)
            return None
        if p == f"repos/o/r/pulls/{self.n}/comments" and not self.inline_ok:
            raise GHError("path is not part of the diff")
        self.next += 1
        c = {"id": self.next, "user": BOT, "body": body["body"], "created_at": "t", "updated_at": "t"}
        if p.endswith("/replies"):
            c["in_reply_to_id"] = int(p.split("/")[-2])
        (self.review if "/pulls/" in p else self.issue).append(c)
        return c


def _with_remote(repo):
    remote = repo.parent / f"{repo.name}-remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "origin", "HEAD:refs/heads/feature")
    return remote


def _remote_log(remote):
    return subprocess.run(["git", "-C", str(remote), "show", "feature:.brief/RATIFICATIONS"],
                          capture_output=True, text=True).stdout


def test_escalate_opens_threads_records_and_is_idempotent(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    remote = _with_remote(repo)
    key = verdicts.key_in_tree(bd, ANCHOR)
    gh = FakeGH()
    done = escalate(gh, "o/r", 7, {"amendments": [_entry(key)]}, repo, bd)
    assert done[0] == f"opened thread: {ANCHOR} ({key})"
    assert gh.review[0]["body"].startswith(f"<!-- brief:amendment {ANCHOR} {key} -->")
    assert _remote_log(remote) == f"{ANCHOR} escalated: amendment={key}\n"
    assert gh.dispatched == [{"ref": "feature", "inputs": {"pr": "7", "base": "main"}}]
    assert escalate(gh, "o/r", 7, {"amendments": [_entry(key)]}, repo, bd) == []
    assert len(gh.review) == 1 and len(gh.dispatched) == 1
    # the bot's commit passes the gate's provenance check, and blocks until answered
    assert any(x.kind == "pending-ratification" and x.blocking for x in check(repo, bd, base=base))


def test_escalate_falls_back_to_a_top_level_comment(tmp_path):
    repo, bd, _ = _amend_pr(tmp_path)
    _with_remote(repo)
    gh = FakeGH(inline_ok=False)
    escalate(gh, "o/r", 7, {"amendments": [_entry(verdicts.key_in_tree(bd, ANCHOR))]}, repo, bd)
    assert not gh.review and f"/ratify {ANCHOR}" in gh.issue[0]["body"]


def _escalated(tmp_path, **kw):
    repo, bd, base = _amend_pr(tmp_path)
    remote = _with_remote(repo)
    gh = FakeGH(**kw)
    key = verdicts.key_in_tree(bd, ANCHOR)
    escalate(gh, "o/r", 7, {"amendments": [_entry(key)]}, repo, bd)
    return repo, bd, base, remote, gh, key


def _event(gh, body, user=VU, reply_to=None, top=False):
    c = {"id": 555, "user": user, "body": body, "html_url": "https://github.com/o/r/pull/7#c555"}
    if top:
        return {"comment": c, "issue": {"number": 7, "pull_request": {}}}
    c["in_reply_to_id"] = reply_to or gh.review[0]["id"]
    return {"comment": c, "pull_request": {"number": 7}}


def test_ratify_in_thread_records_attests_and_passes_verify(tmp_path):
    repo, bd, base, remote, gh, key = _escalated(tmp_path)
    out = command(gh, "o/r", _event(gh, "/ratify"), repo, bd)
    assert out.startswith("recorded ") and f"{ANCHOR} ratified-by: vu1n amendment={key} comment=555" in out
    assert f"ratified-by: vu1n amendment={key}" in _remote_log(remote)
    assert f"<!-- brief:recorded {ANCHOR} {key} ratified vu1n 555 -->" in gh.review[-1]["body"]
    assert len(gh.dispatched) == 2
    [v] = check(repo, bd, base=base)
    assert v.kind == "pending-ratification" and not v.blocking
    assert verify(gh, "o/r", 7, repo, bd, base) == []
    # the bot's reply edited after the fact no longer attests the line
    gh.review[-1]["updated_at"] = "later"
    assert len(verify(gh, "o/r", 7, repo, bd, base)) == 1


def test_ratify_when_the_feature_map_names_a_feature_after_the_anchor(tmp_path):
    # the key is the decision anchor's: editing the feature's Gotchas is not a new version.
    # The map sorts before the decision, as huddles-up's features.md does before native-bots.md.
    repo, bd, base = _amend_pr(tmp_path)
    fmap = bd / "docs" / "0-features.md"
    write(fmap, "---\nid: features\ntype: features\nstatus: active\n---\n"
          f"<!-- brief:anchor {ANCHOR} -->\n## Sandbox\n\n```yaml\npaths:\n  - \"src/sandbox/**\"\n```\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "map")
    remote = _with_remote(repo)
    decision = next(d for d in load_index(bd) if d.doc_id == DOC)
    key = verdicts.amendment_key((bd / "amendments" / f"{ANCHOR}.md").read_text(), decision.anchor(ANCHOR).hash)
    assert verdicts.key_in_tree(bd, ANCHOR) == key
    gh = FakeGH()
    escalate(gh, "o/r", 7, {"amendments": [_entry(key)]}, repo, bd)
    fmap.write_text(fmap.read_text() + "\n### Gotchas\n- new\n")
    _git(repo, "commit", "-qam", "gotcha")
    assert command(gh, "o/r", _event(gh, "/ratify"), repo, bd).startswith("recorded ")
    assert f"ratified-by: vu1n amendment={key}" in _remote_log(remote)


def test_reject_top_level_blocks_the_gate(tmp_path):
    repo, bd, base, remote, gh, key = _escalated(tmp_path)
    out = command(gh, "o/r", _event(gh, f"/reject {ANCHOR} needs a migration plan", top=True), repo, bd)
    assert "rejected-by: vu1n" in out and "needs a migration plan" in out
    [v] = check(repo, bd, base=base)
    assert v.kind == "amendment-rejected" and "needs a migration plan" in v.detail


def test_verify_rejects_a_bot_identity_line_without_a_bot_reply(tmp_path):
    repo, bd, base, remote, gh, key = _escalated(tmp_path)
    _bot_commit(repo, _rec("ratified", key).line())  # an agent faking the bot's git identity
    assert check(repo, bd, base=base)[0].blocking is False  # git alone can't tell
    assert verify(gh, "o/r", 7, repo, bd, base) == [_rec("ratified", key).line()]


def test_command_refusals_record_nothing(tmp_path):
    repo, bd, base, remote, gh, key = _escalated(tmp_path)
    before = _remote_log(remote)
    footer = "/ratify\n\n🤖 Generated by [Claude Code](https://claude.com/claude-code)"
    assert "footer" in command(gh, "o/r", _event(gh, footer), repo, bd)
    assert "bots" in command(gh, "o/r", _event(gh, "/ratify", user=BOT), repo, bd)
    assert "give a reason" in command(gh, "o/r", _event(gh, "/reject"), repo, bd)
    assert "say which amendment" in command(gh, "o/r", _event(gh, "/ratify", top=True), repo, bd)
    assert "no escalated amendment" in command(gh, "o/r", _event(gh, "/ratify other-anchor", top=True), repo, bd)
    assert "not a brief amendment thread" in command(gh, "o/r", _event(gh, "/ratify", reply_to=999), repo, bd)
    gh.perm = "read"
    assert "write" in command(gh, "o/r", _event(gh, "/ratify"), repo, bd)
    gh.perm = "write"
    gh.pr["head"]["repo"] = {"full_name": "fork/r"}
    assert "fork" in command(gh, "o/r", _event(gh, "/ratify"), repo, bd)
    gh.pr["head"]["repo"] = {"full_name": "o/r"}
    # the amendment moved on after the thread showed it: refuse, so nobody ratifies unseen text
    (bd / "amendments" / f"{ANCHOR}.md").write_text("# Amendment\nsomething else\n")
    assert "changed since this thread" in command(gh, "o/r", _event(gh, "/ratify"), repo, bd)
    assert _remote_log(remote) == before and len(gh.dispatched) == 1


def test_ci_template_threads_and_commands():
    wf = yaml.safe_load(CI_WORKFLOW)
    on = wf[True]
    assert on["pull_request_review_comment"] == {"types": ["created"]}
    assert on["issue_comment"] == {"types": ["created"]} and "workflow_dispatch" in on
    gov = wf["jobs"]["govern"]["steps"]
    assert any("brief thread verify" in s.get("run", "") for s in gov)
    assert "brief thread escalate" in wf["jobs"]["escalate"]["steps"][-1]["run"]
    job = wf["jobs"]["verdict"]
    assert "contains(github.event.comment.body, '/ratify')" in job["if"]
    assert "contains(github.event.comment.body, '/reject')" in job["if"]
    assert job["permissions"]["contents"] == "write" and job["permissions"]["actions"] == "write"
    assert "brief thread command --event" in job["steps"][-1]["run"]
    assert job["steps"][0]["with"]["ref"].startswith("refs/pull/")
