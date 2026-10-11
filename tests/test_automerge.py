"""CI merges an amendment PR itself when the model rated every amendment auto-ratifiable and
the rest of the PR is green; the model is then the ratifier, and `ratify --pending` records
it (`ratified_via: model`) only for the amendment versions the triage cleared."""
import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml

from brief import verdicts, versions
from brief.ratify import RatifyError, ratify_and_push, ratify_pending
from brief.templates import CI_WORKFLOW, WATCH_SLOT, ci_workflow
from brief.triage import triage_amendments, verdict
from tests.test_amend_merge import ANCHOR, Fake, _amend_pr
from tests.test_thin import _git, write

DOC = "ADR-001-backend"
WF = yaml.safe_load(CI_WORKFLOW)


def _auto(repo, bd, base, fiat=0.01):
    return verdict(triage_amendments(repo, bd, base, via=Fake(fiat, 0.02)))


# --- the template -------------------------------------------------------------------------

def test_automerge_job_gates():
    job = WF["jobs"]["automerge"]
    assert job["needs"] == "govern"
    cond = job["if"]
    assert "needs.govern.result == 'success' && needs.govern.outputs.verdict == 'auto-ratifiable'" in cond
    assert "vars.BRIEF_AUTO_MERGE != 'off'" in cond
    assert "github.event.pull_request.head.repo.full_name == github.repository" in cond
    assert "!github.event.pull_request.draft" in cond
    # a re-trigger starts a runner only for a same-repo PR whose workflow / app suite passed
    assert "github.event.workflow_run.conclusion == 'success'" in cond
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in cond
    assert "github.event.workflow_run.pull_requests[0] != null" in cond
    assert "github.event.check_suite.conclusion == 'success'" in cond
    assert job["permissions"]["contents"] == "write" and job["permissions"]["pull-requests"] == "write"
    assert job["permissions"]["actions"] == "read"  # the judged run's triage artifact
    assert job["concurrency"]["group"].startswith("brief-merge-${{ github.event.pull_request.number || inputs.pr")
    assert "workflow_run.pull_requests[0].number" in job["concurrency"]["group"]
    assert job["concurrency"]["cancel-in-progress"] is False
    run = job["steps"][0]["run"]
    assert 'gh pr merge "$PR" --repo "$GITHUB_REPOSITORY" --squash --match-head-commit "$SHA"' in run
    assert "local-verified" in run and "needs-ratification" in run
    assert "isCrossRepository" in run and "isDraft" in run and "check-runs" in run and "/status" in run
    assert "sleep" not in run and "seq" not in run  # never holds a runner waiting
    assert job["steps"][0]["env"]["SHA"] == "${{ needs.govern.outputs.sha }}"
    assert WF["jobs"]["govern"]["outputs"]["sha"] == "${{ steps.triage.outputs.sha }}"


def test_govern_keeps_the_verdict_for_a_later_attempt():
    steps = WF["jobs"]["govern"]["steps"]
    triage = next(s for s in steps if s.get("id") == "triage")
    assert "'. + {sha: $sha}'" in triage["run"]  # the verdict names the commit it judged
    up = steps[steps.index(triage) + 1]
    assert up["uses"] == "actions/upload-artifact@v4" and up["with"]["name"] == "brief-triage"
    assert up["with"]["overwrite"] is True


def test_other_workflows_retrigger_the_merge():
    on = WF[True]
    assert on["check_suite"] == {"types": ["completed"]}
    assert "workflow_run" not in on  # nothing else to wait for: the brief run is the last check
    on = yaml.safe_load(ci_workflow(["test", "lint it"]))[True]
    assert on["workflow_run"] == {"workflows": ["test", "lint it"], "types": ["completed"]}
    assert WATCH_SLOT not in ci_workflow(["test"]) and WATCH_SLOT not in ci_workflow()


def test_init_watches_the_repos_pull_request_workflows(tmp_path):
    from brief.init import _pr_workflows

    wfs = tmp_path / ".github" / "workflows"
    wfs.mkdir(parents=True)
    (wfs / "test.yml").write_text("name: test\non:\n  pull_request:\n  push:\n")
    (wfs / "lint.yaml").write_text("on: pull_request\n")
    (wfs / "release.yml").write_text("name: release\non:\n  push:\n")
    (wfs / "brief.yml").write_text("name: brief\non: [pull_request]\n")
    (wfs / "broken.yml").write_text("on: [\n")
    assert _pr_workflows(tmp_path) == [".github/workflows/lint.yaml", "test"]


def test_ratify_job_is_shared_with_automerge():
    job = WF["jobs"]["ratify"]
    assert job["needs"] == ["govern", "automerge"]
    assert job["concurrency"]["group"] == "brief-ratify"
    assert "!cancelled()" in job["if"] and "needs.automerge.outputs.merged == 'true'" in job["if"]
    assert "github.event_name == 'push' && github.actor != 'github-actions[bot]'" in job["if"]
    step = job["steps"][-1]
    # the merging attempt hands over the triage it merged on, whichever event started it
    assert "needs.automerge.outputs.merged == 'true' && needs.automerge.outputs.triage" in step["env"]["TRIAGE"]
    run = step["run"]
    assert 'brief ratify --pending --push --by "$by" "$@"' in run
    assert '--triage "$RUNNER_TEMP/triage.json"' in run and "(merge of #$MERGED_PR)" in run
    assert "git push" not in run  # the push lives in `ratify --push`, one copy for both paths


# --- the merge step, run against a fake `gh` ----------------------------------------------

FAKE_GH = r"""
import json, os, sys
st = json.load(open(os.environ["FAKE_GH"]))
a = sys.argv[1:]
def save(): json.dump(st, open(os.environ["FAKE_GH"], "w"))
if a[:2] == ["pr", "view"]:
    print(json.dumps(st["pr"]))
elif a[:2] == ["pr", "merge"]:
    st["merged"] = a; save()
elif a[:2] == ["run", "download"]:
    triage = st["artifacts"].get(a[2])
    if triage is None:
        sys.exit("no artifact")
    d = a[a.index("--dir") + 1]
    os.makedirs(d, exist_ok=True)
    json.dump(triage, open(os.path.join(d, "triage.json"), "w"))
elif a[0] == "api" and a[-1].endswith("/check-runs"):
    print(json.dumps({"check_runs": st["runs"]}))
elif a[0] == "api" and "/status" in a[1]:
    print(st["status"])
elif a[0] == "api" and "/actions/workflows/brief.yml/runs?head_sha=" in a[1]:
    sha = a[1].split("head_sha=")[1].split("&")[0]
    print(json.dumps({"workflow_runs": [r for r in st["brief_runs"] if r["head_sha"] == sha]}))
elif a[0] == "api" and a[1].endswith("/jobs"):
    run = a[1].split("/runs/")[1].split("/")[0]
    print(json.dumps({"jobs": [{"name": "govern", "conclusion": st["gate"].get(run)}]}))
else:
    sys.exit(f"unexpected gh {a}")
"""


def _run(name, status="completed", conclusion="success", run_id=1):
    return {"name": name, "status": status, "conclusion": conclusion,
            "details_url": f"https://github.com/o/r/actions/runs/{run_id}/job/9"}


AUTO = {"verdict": "auto-ratifiable", "stamp": "s1 clef p=0.010/0.020", "amendments": [], "sha": "abc"}


def _merge(tmp_path, pr=None, runs=None, status="0 pending", retrigger=None):
    """Run the automerge step. `retrigger` (brief_runs, gate, artifacts) starts it as another
    workflow's completion would: no govern outputs, the verdict read back from the judged run."""
    if shutil.which("jq") is None:
        pytest.skip("jq not installed")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "gh.py").write_text(FAKE_GH)
    (bin_ / "gh").write_text(f'#!/bin/sh\nexec {sys.executable} "{bin_ / "gh.py"}" "$@"\n')
    (bin_ / "sleep").write_text(f'#!/bin/sh\ntouch "{tmp_path / "slept"}"\n')
    for f in ("gh", "sleep"):
        (bin_ / f).chmod(0o755)
    state = tmp_path / "gh.json"
    pr = {"state": "OPEN", "isDraft": False, "isCrossRepository": False, "headRefOid": "abc",
          "labels": [], **(pr or {})}
    runs = runs if runs is not None else [_run("govern", run_id=42), _run("pytest", run_id=7)]
    brief_runs, gate, artifacts = retrigger or ([], {}, {})
    state.write_text(json.dumps({"pr": pr, "runs": runs, "status": status, "brief_runs": brief_runs,
                                 "gate": gate, "artifacts": artifacts}))
    out = tmp_path / "out"
    (tmp_path / "temp").mkdir()
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_GH": str(state),
           "PR": "9", "SHA": "", "TRIAGE": "", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "42",
           "WORKFLOW_REF": "o/r/.github/workflows/brief.yml@refs/heads/main",
           "RUNNER_TEMP": str(tmp_path / "temp"),
           "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary")}
    if retrigger is None:
        env.update(SHA="abc", TRIAGE=json.dumps(AUTO))
    else:
        env["GITHUB_RUN_ID"] = "50"  # the workflow_run attempt, on the default branch
    r = subprocess.run(["bash", "-eo", "pipefail", "-c", WF["jobs"]["automerge"]["steps"][0]["run"]],
                       env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "slept").exists()
    st = json.loads(state.read_text())
    return st.get("merged"), (out.read_text() if out.exists() else ""), r.stdout


MERGE = ["pr", "merge", "9", "--repo", "o/r", "--squash", "--match-head-commit", "abc"]


def test_merge_step_merges_when_every_other_check_is_green(tmp_path):
    merged, out, _ = _merge(tmp_path)
    assert merged == MERGE
    assert "merged=true" in out and "pr=9" in out
    assert json.loads(out.split("triage=", 1)[1].splitlines()[0])["stamp"] == AUTO["stamp"]


def test_merge_step_exits_at_once_while_checks_run_and_ignores_its_own_run(tmp_path):
    runs = [_run("pytest", "in_progress", None, 7), _run("brief auto-merge", "in_progress", None, 42)]
    merged, out, stdout = _merge(tmp_path, runs=runs)
    assert merged is None and "merged=true" not in out
    assert "still running on abc: pytest. The next workflow" in stdout  # its own job is not waited on


def test_a_pending_commit_status_exits_at_once(tmp_path):
    merged, _, stdout = _merge(tmp_path, runs=[_run("pytest", run_id=7)], status="1 pending")
    assert merged is None and "still running on abc: commit status." in stdout


def _judged(sha="abc", run_id=30, triage=AUTO, gate="success", older=()):
    runs = [{"id": run_id, "event": "pull_request", "head_sha": sha}, *older]
    arts = {str(run_id): triage} if triage is not None else {}
    gates = {str(run_id): gate}
    for r in older:
        arts.setdefault(str(r["id"]), AUTO)
        gates.setdefault(str(r["id"]), "success")
    return runs, gates, arts


def test_a_completion_event_merges_the_judged_head(tmp_path):
    # the judged brief run (30) is still finishing; only the other checks count
    runs = [_run("pytest", run_id=7), _run("brief auto-merge", "in_progress", None, 30)]
    merged, out, _ = _merge(tmp_path, runs=runs, retrigger=_judged())
    assert merged == MERGE
    assert "merged=true" in out and "pr=9" in out
    assert json.loads(out.split("triage=", 1)[1].splitlines()[0])["verdict"] == "auto-ratifiable"


@pytest.mark.parametrize("judged,why", [
    (([], {}, {}), "no brief run judged abc"),
    (_judged(sha="old"), "no brief run judged abc"),
    (_judged(gate="failure"), "the gate has not passed on abc"),
    (_judged(gate=None), "the gate has not passed on abc"),
    (_judged(triage=None), "kept no triage for abc"),
    (_judged(triage={**AUTO, "verdict": "escalate", "stamp": ""}), "abc was not judged auto-ratifiable"),
    (_judged(triage={**AUTO, "verdict": "none"}), "abc was not judged auto-ratifiable"),
    (_judged(triage={**AUTO, "sha": "old"}), "abc was not judged auto-ratifiable"),
    # the newest verdict on the head counts, not any earlier auto-ratifiable one
    (_judged(triage={**AUTO, "verdict": "escalate"}, older=[{"id": 20, "event": "pull_request", "head_sha": "abc"}]),
     "abc was not judged auto-ratifiable"),
])
def test_a_retrigger_never_merges_an_unjudged_head(tmp_path, judged, why):
    merged, out, stdout = _merge(tmp_path, retrigger=judged)
    assert merged is None and "merged=true" not in out
    assert why in stdout


@pytest.mark.parametrize("pr,runs,status,why", [
    ({"isCrossRepository": True}, None, "0 pending", "fork"),
    ({"isDraft": True}, None, "0 pending", "draft"),
    ({"labels": [{"name": "needs-ratification"}]}, None, "0 pending", "labelled"),
    ({"labels": [{"name": "local-verified"}]}, None, "0 pending", "labelled"),
    ({"headRefOid": "def"}, None, "0 pending", "head moved"),
    ({"state": "MERGED"}, None, "0 pending", "not open"),  # the other attempt merged it first
    (None, [_run("pytest", conclusion="failure", run_id=7)], "0 pending", "checks not green: pytest"),
    (None, [_run("pytest", conclusion="failure", run_id=7), _run("lint", "queued", None, 8)], "0 pending",
     "checks not green: pytest"),
    (None, None, "2 failure", "commit status is failure"),
])
def test_merge_step_skips(tmp_path, pr, runs, status, why):
    merged, out, stdout = _merge(tmp_path, pr=pr, runs=runs, status=status)
    assert merged is None and "merged=true" not in out
    assert why in stdout


def test_a_failed_check_skips_a_retrigger_too(tmp_path):
    runs = [_run("pytest", conclusion="failure", run_id=7)]
    merged, _, stdout = _merge(tmp_path, runs=runs, retrigger=_judged())
    assert merged is None and "checks not green: pytest" in stdout


# --- ratify --pending on the model's verdict ------------------------------------------------

def test_model_ratification_is_stamped_as_the_model(tmp_path):
    repo, bd, base = _amend_pr(tmp_path, code=True)
    out = _auto(repo, bd, base)
    [r] = ratify_pending(bd, by=f"{out['stamp']} (merge of #9)", model=out)
    archived = open(r.archived).read()
    assert "ratified_by: s1 clef p=0.010/0.020 (merge of #9)" in archived
    assert "ratified_via: model" in archived
    assert versions.latest_rev(bd, DOC) == 2


def test_human_merge_is_stamped_human(tmp_path):
    repo, bd, _ = _amend_pr(tmp_path)
    [r] = ratify_pending(bd, by="vu (merge of #7)")
    assert "ratified_via: human" in open(r.archived).read()


def test_model_ratifies_only_the_version_it_cleared(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    out = _auto(repo, bd, base)
    # the amendment changed after the triage judged it: not the model's to ratify
    (bd / "amendments" / f"{ANCHOR}.md").write_text("# Amendment\nsomething else\n")
    held = []
    assert ratify_pending(bd, by=f"{out['stamp']} (merge of #9)", held=held, model=out) == []
    assert held and "not cleared by the model" in held[0]
    assert versions.latest_rev(bd, DOC) == 1


def test_one_escalated_amendment_means_no_model_ratification(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    live = versions.live_doc(bd, DOC)
    live.write_text(live.read_text() + "\n<!-- brief:anchor docker-flag -->\n## Docker flag\nOff by default.\n")
    write(bd / "amendments" / "docker-flag.md", "# Amendment\nadd the flag\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second anchor")
    rated = triage_amendments(repo, bd, base, via=Fake(0.01, 0.02))
    rated[0].fiat = 0.7  # the model would escalate one of the two
    out = verdict(rated)
    assert out["verdict"] == "escalate" and out["stamp"] == ""
    assert "needs.govern.outputs.verdict == 'auto-ratifiable'" in WF["jobs"]["automerge"]["if"]
    with pytest.raises(RatifyError, match="not auto-ratifiable"):
        ratify_pending(bd, by="s1 clef (merge of #9)", model=out)
    # a forged all-auto entry for only one anchor still holds the doc
    out = verdict([a for a in rated[1:]])
    held = []
    assert ratify_pending(bd, by=f"{out['stamp']} (merge of #9)", held=held, model=out) == []
    assert any("not cleared by the model" in h for h in held)


def test_model_ratification_needs_the_triage_stamp(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    out = _auto(repo, bd, base)
    with pytest.raises(RatifyError, match="--by must start with"):
        ratify_pending(bd, by="vu (merge of #9)", model=out)


def test_human_ratified_anchor_in_a_model_merge_keeps_the_human(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    out = _auto(repo, bd, base)
    key = verdicts.key_in_tree(bd, ANCHOR)
    write(bd / verdicts.RECORDS, verdicts.Record(ANCHOR, "ratified", key, "vu1n", "11", "https://x/11").line() + "\n")
    [r] = ratify_pending(bd, by=f"{out['stamp']} (merge of #9)", model=out)
    archived = open(r.archived).read()
    assert "ratified_by: vu1n via /ratify (https://x/11); s1 clef" in archived and "ratified_via: human" in archived


# --- ratify --push: the shared commit-and-push ----------------------------------------------

def _main_with_remote(repo):
    remote = repo.parent / f"{repo.name}-remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "checkout", "-qB", "main")
    _git(repo, "push", "-q", "origin", "main")
    return remote


def _show(remote, what):
    return subprocess.run(["git", "-C", str(remote), "log", "-1", f"--format={what}", "main"],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_ratify_and_push_commits_as_the_bot(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    out = _auto(repo, bd, base)
    remote = _main_with_remote(repo)
    done, held = ratify_and_push(repo, bd, f"{out['stamp']} (merge of #9)", out)
    assert [r.anchor for r in done] == [ANCHOR] and held == []
    assert _show(remote, "%ae %ce") == f"{verdicts.BOT_EMAIL} {verdicts.BOT_EMAIL}"
    assert _show(remote, "%s") == "brief: ratify amendments (s1 clef p=0.010/0.020 (merge of #9))"
    assert ratify_and_push(repo, bd, "again") == ([], [])  # nothing pending: no commit


def test_ratify_and_push_redoes_on_a_moved_branch(tmp_path):
    repo, bd, _ = _amend_pr(tmp_path)
    remote = _main_with_remote(repo)
    other = repo.parent / f"{repo.name}-other"
    subprocess.run(["git", "clone", "-q", "-b", "main", str(remote), str(other)], check=True)
    _git(other, "config", "user.email", "o@o")
    _git(other, "config", "user.name", "o")
    write(other / "README.md", "moved\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-qm", "someone else's push")
    _git(other, "push", "-q", "origin", "main")
    done, _ = ratify_and_push(repo, bd, "vu (merge of #7)")
    assert [r.anchor for r in done] == [ANCHOR]
    assert _show(remote, "%s").startswith("brief: ratify amendments")
    assert subprocess.run(["git", "-C", str(remote), "show", "main:README.md"],
                          capture_output=True, text=True).stdout == "moved\n"


def test_cli_ratify_triage_flag(tmp_path):
    repo, bd, base = _amend_pr(tmp_path)
    out = _auto(repo, bd, base)
    f = tmp_path / "triage.json"
    f.write_text(json.dumps(out))
    r = subprocess.run(["brief", "ratify", "--pending", "--triage", str(f), "--by", f"{out['stamp']} (merge of #9)",
                        "--brief", str(bd)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    archived = (bd / "amendments" / "archive" / f"{ANCHOR}-v0002.md").read_text()
    assert "ratified_via: model" in archived
    r = subprocess.run(["brief", "ratify", ANCHOR, "--push", "--brief", str(bd)], capture_output=True, text=True)
    assert r.returncode == 2


def test_an_anchor_escalated_on_this_pr_never_turns_auto(tmp_path):
    from tests.test_threads import _bot_commit

    repo, bd, base = _amend_pr(tmp_path)
    _bot_commit(repo, verdicts.Record(ANCHOR, "escalated", verdicts.key_in_tree(bd, ANCHOR)).line())
    # the agent rewords the amendment; the model now likes it
    (bd / "amendments" / f"{ANCHOR}.md").write_text("# Amendment\nadmit docker behind an off-by-default flag\n")
    _git(repo, "commit", "-qam", "reword")
    out = _auto(repo, bd, base)
    assert out["verdict"] == "escalate" and "escalated earlier" in out["amendments"][0]["why"]
    # an escalation from an earlier PR (already on the base) doesn't hold a new amendment
    from tests.test_thin import _published_repo

    (tmp_path / "b").mkdir()
    repo2, bd2 = _published_repo(tmp_path / "b")
    _bot_commit(repo2, verdicts.Record(ANCHOR, "escalated", "0" * 12).line())
    base2 = subprocess.run(["git", "-C", str(repo2), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    live = versions.live_doc(bd2, DOC)
    live.write_text(live.read_text().replace("is deleted", "is admitted behind a flag"))
    write(bd2 / "amendments" / f"{ANCHOR}.md", "# Amendment\nadmit docker behind a flag\n")
    _git(repo2, "add", "-A")
    _git(repo2, "commit", "-qm", "next pr")
    assert _auto(repo2, bd2, base2)["verdict"] == "auto-ratifiable"
