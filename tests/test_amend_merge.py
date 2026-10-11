"""Merging the amendment PR is the ratification: on a PR range a locked-decision edit that
carries its amendment is pending-ratification (non-blocking); CI's `ratify --pending`
publishes it after the merge. A bare edit, a published revision, or a staged commit stays blocked."""
import subprocess
from types import SimpleNamespace as NS

import yaml

from brief import versions
from brief.gate import check
from brief.ratify import ratify_pending
from brief.templates import CI_WORKFLOW
from brief.triage import triage_amendments, verdict

from tests.test_thin import _git, _published_repo, write

ANCHOR = "sandbox-backend-single-only"


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _amend_pr(tmp_path, amendment=True, signoff=True, code=False):
    """A branch commit that edits the locked decision, optionally with its amendment."""
    repo, bd = _published_repo(tmp_path)
    base = _head(repo)
    live = versions.live_doc(bd, "ADR-001-backend")
    live.write_text(live.read_text().replace("is deleted", "is admitted behind a flag"))
    if amendment:
        write(bd / "amendments" / f"{ANCHOR}.md", "# Amendment\nadmit docker behind a flag: a customer needs it\n")
    if signoff:
        write(bd / "SIGNOFF", f"{ANCHOR} amend-proposed: admit docker behind a flag\n")
    if code:
        write(repo / "src" / "sandbox" / "mod.rs", "// docker behind a flag\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "amend")
    return repo, bd, base


def test_decision_edit_with_amendment_is_pending_not_blocking(tmp_path):
    repo, bd, base = _amend_pr(tmp_path, code=True)
    v = check(repo, bd, base=base)
    assert {x.kind for x in v} == {"pending-ratification"}
    [p] = v
    assert p.anchor_id == ANCHOR and not p.blocking
    assert p.files == [".brief/docs/ADR-001-backend.md"]


def test_bare_decision_edit_is_still_ratified_edit(tmp_path):
    repo, bd, base = _amend_pr(tmp_path, amendment=False)
    v = check(repo, bd, base=base)
    assert any(x.kind == "ratified-edit" and x.blocking for x in v)
    assert not any(x.kind == "pending-ratification" for x in v)


def test_amendment_for_one_anchor_does_not_cover_another(tmp_path):
    repo, bd = _published_repo(tmp_path)
    base = _head(repo)
    live = versions.live_doc(bd, "ADR-001-backend")
    live.write_text(live.read_text() + "\n<!-- brief:anchor docker-ok -->\n## Docker is fine\n")
    write(bd / "amendments" / f"{ANCHOR}.md", "# Amendment\nreword\n")  # but ANCHOR's text is unchanged
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "sneak")
    kinds = {x.kind for x in check(repo, bd, base=base)}
    assert "ratified-edit" in kinds and "pending-ratification" not in kinds


def test_published_revision_stays_blocked_even_with_amendment(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    v1 = versions.version_path(bd, "ADR-001-backend", 1)
    v1.write_text(v1.read_text().replace("is deleted", "is back"))
    _git(repo, "commit", "-qam", "rewrite v1")
    assert any(x.kind == "ratified-edit" and x.blocking for x in check(repo, bd, base=base))


def test_minting_a_revision_in_the_pr_is_not_pending(tmp_path):
    # only ratification publishes; a hand-published v2 would make the merge look ratified
    repo, bd, base = _amend_pr(tmp_path)
    versions.publish(bd, "ADR-001-backend")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "publish")
    assert "ratified-edit" in {x.kind for x in check(repo, bd, base=base)}


def test_staged_amendment_edit_still_blocks(tmp_path):
    repo, bd = _published_repo(tmp_path)
    live = versions.live_doc(bd, "ADR-001-backend")
    live.write_text(live.read_text().replace("is deleted", "is back"))
    write(bd / "amendments" / f"{ANCHOR}.md", "# Amendment\n")
    _git(repo, "add", "-A")
    [p] = [x for x in check(repo, bd) if x.kind == "pending-ratification"]
    assert p.blocking


def test_cli_exit_codes(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    r = subprocess.run(["brief", "check", "--repo", str(repo), "--base", base], capture_output=True, text=True)
    assert r.returncode == 0 and "pending ratification" in r.stdout


def test_ratify_pending_after_merge(tmp_path):
    repo, bd, _ = _amend_pr(tmp_path)
    write(bd / "amendments" / "other-anchor.md", "# a proposal still waiting for its text\n")
    [r] = ratify_pending(bd, by="vu (merge of #7)")
    assert (r.doc_id, r.anchor, r.rev) == ("ADR-001-backend", ANCHOR, 2)
    assert versions.version_path(bd, "ADR-001-backend", 2).read_text() == versions.live_doc(bd, "ADR-001-backend").read_text()
    archived = (bd / "amendments" / "archive" / f"{ANCHOR}-v0002.md").read_text()
    assert "ratified_rev: 0002" in archived and "ratified_by: vu (merge of #7)" in archived
    assert not (bd / "amendments" / f"{ANCHOR}.md").exists()
    assert (bd / "amendments" / "other-anchor.md").exists()
    assert ratify_pending(bd, by="again") == []  # idempotent: a re-run finds nothing


def test_ratify_pending_leaves_proposal_without_decision_text(tmp_path):
    repo, bd = _published_repo(tmp_path)
    write(bd / "amendments" / f"{ANCHOR}.md", "# proposal only\n")
    assert ratify_pending(bd, by="vu") == []
    assert versions.latest_rev(bd, "ADR-001-backend") == 1


def test_ci_template_ratifies_on_push_to_main():
    wf = yaml.safe_load(CI_WORKFLOW)
    on = wf[True]  # YAML 1.1 reads the `on` key as True
    assert "pull_request" in on and on["push"]["branches"] == ["main"]
    job = wf["jobs"]["ratify"]
    assert job["permissions"]["contents"] == "write"
    assert "github-actions[bot]" in job["if"] and "push" in job["if"]
    run = job["steps"][-1]["run"]
    assert "brief ratify --pending --by" in run and "merge of #$pr" in run
    assert "git status --porcelain" in run and "git push" in run
    assert wf["jobs"]["govern"]["if"] == "github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch'"
    esc = wf["jobs"]["escalate"]
    assert esc["if"].startswith("needs.govern.outputs.verdict == 'escalate'")
    assert "--add-label needs-ratification" in esc["steps"][-1]["run"]
    triage = next(s for s in wf["jobs"]["govern"]["steps"] if s.get("id") == "triage")
    assert "BRIEF_S1=off" in triage["run"] and "--amendments --json" in triage["run"]
    assert set(triage["env"]) == {"TYPESAFE_API_KEY", "TYPESAFE_BASE_URL", "TYPESAFE_DEFAULT_MODEL"}


class Fake:
    def __init__(self, fiat, impact=0.01, model="clef"):
        self.fiat, self.impact, self.model, self.calls = fiat, impact, model, []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        if self.fiat == "error":
            raise OSError("down")
        return NS(model=self.model, answers={"fiat": NS(type="noul", noul=self.fiat),
                                             "impact": NS(type="noul", noul=self.impact)})


def test_amendment_triage_auto_ratifiable_writes_nothing(tmp_path):
    repo, bd, base = _amend_pr(tmp_path, code=True)
    fake = Fake(0.01, 0.02)
    rated = triage_amendments(repo, bd, base, via=fake)
    [a] = rated
    assert (a.anchor_id, a.fiat, a.impact, a.model) == (ANCHOR, 0.01, 0.02, "clef") and a.auto
    out = verdict(rated)
    assert out["verdict"] == "auto-ratifiable" and out["stamp"] == "s1 clef p=0.010/0.020"
    state, questions = fake.calls[0]
    assert "admitted behind a flag" in state["decision_change"]
    assert "a customer needs it" in state["amendment"] and "docker behind a flag" in state["code_diff"]
    assert set(questions) == {"fiat", "impact"}
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                          capture_output=True, text=True).stdout == ""
    # the stamp a model-made merge would record
    [r] = ratify_pending(bd, by=f"{out['stamp']} (merge of #9)")
    assert "ratified_by: s1 clef p=0.010/0.020 (merge of #9)" in open(r.archived).read()


def test_amendment_triage_escalates_reversal_or_impact(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    reversal = verdict(triage_amendments(repo, bd, base, via=Fake(0.7, 0.01)))
    assert reversal["verdict"] == "escalate" and reversal["stamp"] == ""
    assert "reverse or weaken" in reversal["amendments"][0]["why"]
    impact = verdict(triage_amendments(repo, bd, base, via=Fake(0.01, 0.4)))
    assert impact["verdict"] == "escalate" and "high-impact" in impact["amendments"][0]["why"]


def test_amendment_triage_fails_closed(tmp_path, monkeypatch):
    repo, bd, base = _amend_pr(tmp_path)
    for fake in (Fake("error"), Fake(None), Fake(0.01, float("nan")), Fake(0.01, None)):
        out = verdict(triage_amendments(repo, bd, base, via=fake))
        assert out["verdict"] == "escalate", fake.__dict__
        assert "no model opinion" in out["amendments"][0]["why"]
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert verdict(triage_amendments(repo, bd, base))["verdict"] == "escalate"


def test_no_pending_amendment_is_no_verdict(tmp_path):
    repo, bd = _published_repo(tmp_path)
    base = _head(repo)
    write(repo / "src" / "sandbox" / "mod.rs", "// tweak\n")
    _git(repo, "commit", "-qam", "code")
    assert verdict(triage_amendments(repo, bd, base, via=Fake(0.01)))["verdict"] == "none"


def test_cli_triage_json(tmp_path, monkeypatch):
    import json

    repo, bd, base = _amend_pr(tmp_path)
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("TYPESAFE")}
    r = subprocess.run(["brief", "triage", "--amendments", "--json", "--repo", str(repo), "--base", base],
                       capture_output=True, text=True, env=env)
    out = json.loads(r.stdout)
    assert out["verdict"] == "escalate" and "needs-ratification" in out["summary"]


def test_moving_latest_in_the_pr_is_not_pending(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    (bd / "aliases.yaml").write_text("ADR-001-backend:\n  latest: 7\n")
    _git(repo, "commit", "-qam", "alias")
    assert "ratified-edit" in {x.kind for x in check(repo, bd, base=base)}
