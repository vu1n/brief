"""CI triage authenticates to the kypp Worker with the job's GitHub Actions OIDC token, so a
governed repo needs no secret; a TYPESAFE_API_KEY secret still wins, and anything missing
or failing escalates (BRIEF_S1=off)."""
import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml
from typer.testing import CliRunner

from brief.cli import app
from brief.init import init_vault
from brief.templates import CI_WORKFLOW, DEFAULT_KYPP_URL, baked_kypp_url, ci_workflow, kypp_url

URL = "https://kypp.owner.workers.dev"
WF = yaml.safe_load(CI_WORKFLOW)


def _step(wf):
    return next(s for s in wf["jobs"]["govern"]["steps"] if s.get("id") == "triage")


def test_only_the_govern_job_may_mint_an_oidc_token():
    for name, job in WF["jobs"].items():
        perms = job.get("permissions", {})
        assert (perms.get("id-token") == "write") == (name == "govern"), name


def test_defaults_are_clef_and_the_baked_kypp_url_and_repo_vars_win():
    env = _step(yaml.safe_load(ci_workflow(kypp=URL + "/")))["env"]
    assert env["TYPESAFE_BASE_URL"] == f"${{{{ vars.TYPESAFE_BASE_URL || '{URL}' }}}}"
    assert env["TYPESAFE_DEFAULT_MODEL"] == "${{ vars.TYPESAFE_DEFAULT_MODEL || 'clef' }}"
    assert env["TYPESAFE_API_KEY"] == "${{ secrets.TYPESAFE_API_KEY }}"
    assert baked_kypp_url(ci_workflow(kypp=URL)) == URL and baked_kypp_url(CI_WORKFLOW) == DEFAULT_KYPP_URL
    # --kypp-url "" bakes none: the repo variable is then the only source
    assert _step(yaml.safe_load(ci_workflow(kypp="")))["env"]["TYPESAFE_BASE_URL"] == "${{ vars.TYPESAFE_BASE_URL }}"


@pytest.mark.parametrize("bad", ["http://kypp.x", "https://x' }} evil", "kypp.x", "https://x/$(id)"])
def test_a_kypp_url_that_could_break_the_workflow_is_refused(bad):
    with pytest.raises(ValueError):
        kypp_url(bad)
    with pytest.raises(ValueError):
        ci_workflow(kypp=bad)


FAKE_CURL = r"""#!/bin/sh
echo "$@" >> "$LOG/curl"
[ -n "$CURL_FAIL" ] && exit 22
printf '{"count":1,"value":"oidc.jwt.sig"}'
"""

# Stands in for `uvx ... brief triage`: records what the triage would see, answers escalate.
FAKE_UVX = r"""#!/bin/sh
printf '{"key":"%s","base":"%s","model":"%s","s1":"%s"}' "$TYPESAFE_API_KEY" "$TYPESAFE_BASE_URL" \
  "$TYPESAFE_DEFAULT_MODEL" "${BRIEF_S1:-}" > "$LOG/uvx"
printf '{"verdict":"escalate","summary":"s"}'
"""


def _triage(tmp_path, **env_over):
    """Run the triage step's shell; returns (what uvx saw, curl's argv lines, step stdout)."""
    if shutil.which("jq") is None:
        pytest.skip("jq not installed")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in (("curl", FAKE_CURL), ("uvx", FAKE_UVX)):
        (bin_ / name).write_text(body)
        (bin_ / name).chmod(0o755)
    log = tmp_path / "log"
    log.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"],
                   cwd=repo, check=True)
    (tmp_path / "temp").mkdir()
    env = {"PATH": f"{bin_}:{os.environ['PATH']}", "LOG": str(log), "BASE": "main",
           "RUNNER_TEMP": str(tmp_path / "temp"), "GITHUB_OUTPUT": str(tmp_path / "out"),
           "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
           "TYPESAFE_API_KEY": "", "TYPESAFE_BASE_URL": URL + "/", "TYPESAFE_DEFAULT_MODEL": "clef",
           "ACTIONS_ID_TOKEN_REQUEST_URL": "https://pipelines.example/idtoken?api-version=2.0",
           "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "req-token"}
    env.update(env_over)
    env = {k: v for k, v in env.items() if v is not None}
    r = subprocess.run(["bash", "-eo", "pipefail", "-c", _step(WF)["run"]], cwd=repo, env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    curl = (log / "curl").read_text().splitlines() if (log / "curl").exists() else []
    return json.loads((log / "uvx").read_text()), curl, r.stdout


def test_no_secret_means_an_oidc_token_for_the_worker_url(tmp_path):
    seen, curl, out = _triage(tmp_path)
    assert seen == {"key": "oidc.jwt.sig", "base": URL, "model": "clef", "s1": ""}
    assert len(curl) == 1
    assert "https://pipelines.example/idtoken?api-version=2.0&audience=https%3A%2F%2Fkypp.owner.workers.dev" in curl[0]
    assert "Authorization: bearer req-token" in curl[0]
    assert "::add-mask::oidc.jwt.sig" in out


def test_a_secret_wins_over_oidc(tmp_path):
    seen, curl, _ = _triage(tmp_path, TYPESAFE_API_KEY="sk-repo", REPO_BASE_URL=URL)
    assert seen["key"] == "sk-repo" and seen["s1"] == "" and curl == []


def test_a_secret_never_goes_to_the_baked_url(tmp_path):
    # secret but no TYPESAFE_BASE_URL repo variable: the baked kypp URL gets an OIDC token instead
    seen, curl, _ = _triage(tmp_path, TYPESAFE_API_KEY="sk-repo")
    assert seen["key"] == "oidc.jwt.sig" and len(curl) == 1


@pytest.mark.parametrize("over", [
    {"ACTIONS_ID_TOKEN_REQUEST_URL": None, "ACTIONS_ID_TOKEN_REQUEST_TOKEN": None},  # fork PR
    {"CURL_FAIL": "1"},                                                              # token endpoint error
    {"TYPESAFE_BASE_URL": ""},                                                       # no kypp URL anywhere
])
def test_no_token_escalates(tmp_path, over):
    seen, curl, _ = _triage(tmp_path, **over)
    assert seen["key"] == "" and seen["s1"] == "off"
    if over.get("TYPESAFE_BASE_URL") == "":
        assert curl == []


def test_init_bakes_keeps_and_clears_the_kypp_url(tmp_path):
    wf = tmp_path / ".github" / "workflows" / "brief.yml"
    init_vault(tmp_path, ci=True, kypp_url=URL)
    assert baked_kypp_url(wf.read_text()) == URL
    init_vault(tmp_path, ci=True)  # a re-run (an upgrade) keeps it
    assert baked_kypp_url(wf.read_text()) == URL
    init_vault(tmp_path, ci=True, kypp_url="")
    assert baked_kypp_url(wf.read_text()) is None


def test_cli_kypp_url_flag(tmp_path):
    r = CliRunner().invoke(app, ["init", "--repo", str(tmp_path), "--ci", "--kypp-url", URL + "/"])
    assert r.exit_code == 0, r.output
    assert baked_kypp_url((tmp_path / ".github" / "workflows" / "brief.yml").read_text()) == URL
    r = CliRunner().invoke(app, ["init", "--repo", str(tmp_path), "--ci", "--kypp-url", "http://x"])
    assert r.exit_code != 0


def test_the_rendered_step_is_valid_shell():
    if sys.platform == "win32":
        pytest.skip("bash")
    subprocess.run(["bash", "-n", "-c", _step(yaml.safe_load(ci_workflow(kypp=URL)))["run"]], check=True)
