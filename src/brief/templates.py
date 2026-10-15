"""Canonical text injected by `brief init` — the always-on governance floor.

This is the *behavior layer*: short, self-sufficient (works with zero skills, any
harness), and the thing the pilot proved does the heavy lifting. Keep it tight.
"""

MARKER = "## Context Vault (brief)"

AGENTS_SNIPPET = """\
## Context Vault (brief)

Architectural decisions live in `.brief/docs/` as governance docs. Each has a stable
anchor (`<!-- brief:anchor id -->`), a `status`, and the code it governs (`related_code`
globs). A decision is addressable as `doc://<project>/<doc-id>@latest#<anchor>` — resolve
one with `brief resolve <ref>` to read the exact decision; don't infer it from the ref.

Decisions are **ratified constraints on code, not editable notes**. They bind the code you
write, not the questions you are asked. When the task is to explore, evaluate or compare
(is X simpler? should we switch to Y?), treat decisions as context, not constraints: judge
the option on its merits, say plainly where it beats the current design, and name the
decisions it would reverse. A decision records what was chosen and why at the time; it
may have been wrong, or the situation may have changed, so say so when you see it.
Reversing one goes through an amendment when the work lands, so a decision is never by
itself a reason to rule an option out.

When you change code, develop *to* them:

- A decision with `status: active` is READ-ONLY to coding work. Do NOT edit it to make
  your change fit — your code conforms to the decision, not the reverse.
- If `brief check` asks for a sign-off (only decisions marked `signoff: required` do, and
  only when you touch the code under their `// Context:` comment) and your change STILL
  satisfies the decision, record `<anchor-id> conforms: <reason>` in `.brief/SIGNOFF`.
  `brief triage` (optional System One model) writes that line itself for the asks it
  rates as clearly conforming; read and answer the ones it leaves.
- If the task CANNOT be done without changing a ratified decision, you may NOT change it
  on your own authority. Write `.brief/amendments/<anchor-id>.md` (what should change and
  why), record `<anchor-id> amend-proposed: <reason>` in `.brief/SIGNOFF`, and STOP — it
  needs ratification before code can land. The amendment PR may also carry the
  proposed decision text (one amendment per anchor it changes); merging that PR is the
  ratification (a human's, or CI's when the model rates every amendment low-risk; you
  never merge it). If CI escalates an amendment, it opens a PR thread for it: answer
  questions there, never `/ratify` it yourself, and never edit `.brief/RATIFICATIONS`. On
  `/reject`, revise the amendment to meet the reason, or withdraw it. Never bypass the
  commit hook.
- If conforming takes workarounds (contorted code, duplicated paths, a feature you can't
  build cleanly), still conform, but say so: tell the person you work for that the
  decision may be out of date and what it is costing, or propose an amendment. Don't keep
  coding in circles around a rule that no longer fits.
- At each site that embodies a decision, leave a one-line comment:
  `// Context: doc://<project>/<doc-id>@latest#<anchor> — <the rule, in one line>`.
  The ref makes it checkable; the one-line rule puts the constraint in front of the next
  agent exactly where it touches the code. Keep the full reasoning in the decision doc.
- If your memory, notes, or habits disagree with an active decision about how the code
  behaves, the decision wins:
  it is versioned and reviewed with the code, memory is not. Follow the decision and say
  which memory looked stale.

If the repo has a feature map (a `.brief/docs` doc with `type: features`), run
`brief features <files>` before changing code and read the Gotchas of each feature you
touch. When you move or delete code, update that feature's `paths:` in the same change;
when you hit a trap the next agent would hit too, add it to the feature's Gotchas.

**Before committing, run `brief check`** (resolve anything it flags) and `brief pin`
(freeze any `@latest`/`@current` refs you wrote to a concrete revision). CI runs the same
check on PRs — that is the backstop; don't bypass it.

**After authoring/publishing a decision — or before opening a PR — run `brief doctor`**
and close what it flags (wire a `// Context:` ref into governed code, pin a floating ref,
publish a draft you now rely on, re-verify a ref the latest revision made stale). It is
advisory, not a gate: it exists so *you* catch latent drift instead of leaving it for a
human to notice later.
"""

import json
import re

from . import __version__

# Installed from a pinned tag, never from PyPI: `brief` on PyPI is an unrelated package, and
# an unpinned source would let any push to brief's main change every governed repo's gate.
BRIEF_REPO = "https://github.com/vu1n/brief"
BRIEF_SOURCE = f"git+{BRIEF_REPO}@v{__version__}"
CI_MARKER = "# Managed by `brief init --ci`: re-running it rewrites this file. Delete this line to own it."

# The kypp Worker that answers `brief triage` in CI with Clef (POST /v1/systemone), taking the
# job's GitHub Actions OIDC token as the bearer. It must equal that Worker's KYPP_PUBLIC_URL (the
# token's audience), and the Worker only accepts owners in its KYPP_OIDC_OWNERS. Override per repo
# with `brief init --ci --kypp-url https://<worker>` or the TYPESAFE_BASE_URL repo variable (which wins).
DEFAULT_KYPP_URL = "https://kypp.vu1n.dev"
KYPP_SLOT = "__BRIEF_KYPP_URL__"  # ci_workflow fills it
_KYPP_URL_RE = re.compile(r"https://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~/-]*)?")
_BAKED_RE = re.compile(r"vars\.TYPESAFE_BASE_URL \|\| '([^']*)'")

# Where `ci_workflow` lists the repo's other PR workflows: their completion retries the
# auto-merge (workflow_run must name workflows; there is no wildcard).
WATCH_SLOT = "  # brief: workflow_run on the repo's other PR workflows goes here (`brief init --ci`)\n"

CI_TEMPLATE = f"""\
{CI_MARKER}
name: brief
on:
  pull_request:
  push:
    branches: [main]      # merging an amendment PR ratifies it (the ratify job)
  pull_request_review_comment:
    types: [created]      # a maintainer's /ratify or /reject in an amendment thread
  issue_comment:
    types: [created]      # ... or top-level: /ratify <anchor>, /reject <anchor> <reason>
  check_suite:
    types: [completed]    # a third-party CI app finished: retry the auto-merge (Actions' own suites never fire this)
  workflow_dispatch:      # the bot's verdict commits start no run, so it dispatches one
    inputs:
      pr:
        required: true
      base:
        required: true
{WATCH_SLOT}jobs:
  govern:
    if: github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: read
      id-token: write         # the triage step's OIDC token for the System One endpoint (kypp)
    env:
      BASE: ${{{{ github.base_ref || inputs.base }}}}
      PR: ${{{{ github.event.pull_request.number || inputs.pr }}}}
    outputs:
      verdict: ${{{{ steps.triage.outputs.verdict }}}}
      triage: ${{{{ steps.triage.outputs.triage }}}}
      sha: ${{{{ steps.triage.outputs.sha }}}}     # the commit the gate and triage judged
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{{{ github.event.pull_request.head.sha || github.sha }}}}
          fetch-depth: 0          # need the base ref for the range check
      - uses: astral-sh/setup-uv@v5
      - name: verdicts in .brief/RATIFICATIONS match the bot's own PR replies
        env:
          GH_TOKEN: ${{{{ github.token }}}}
        run: uvx --from {BRIEF_SOURCE} brief thread verify --pr "$PR" --base "origin/$BASE"
      - name: brief governance gate
        # pinned; upgrade by re-running `brief init --ci` from a newer brief
        run: uvx --from {BRIEF_SOURCE} brief check --base "origin/$BASE"
      - name: brief amendment triage (auto-ratifiable or escalate)
        id: triage
        # Optional System One model. Sends the decision edit, amendment and governed diff to
        # TYPESAFE_BASE_URL: the kypp Worker (Clef) unless repo variables say otherwise. The
        # bearer is a TYPESAFE_API_KEY secret if the repo has one and names its own URL (the
        # secret never goes to the default kypp URL), else a GitHub Actions OIDC token whose
        # audience is that URL (no secret needed). No URL, no token (a fork PR gets none) or any
        # error = escalate.
        env:
          TYPESAFE_API_KEY: ${{{{ secrets.TYPESAFE_API_KEY }}}}
          TYPESAFE_BASE_URL: ${{{{ vars.TYPESAFE_BASE_URL{KYPP_SLOT} }}}}
          TYPESAFE_DEFAULT_MODEL: ${{{{ vars.TYPESAFE_DEFAULT_MODEL || 'clef' }}}}
          REPO_BASE_URL: ${{{{ vars.TYPESAFE_BASE_URL }}}}
        run: |
          TYPESAFE_BASE_URL="${{TYPESAFE_BASE_URL%/}}"
          if [ -z "$REPO_BASE_URL" ]; then TYPESAFE_API_KEY=""; fi   # a secret only goes where the repo points it
          if [ -z "$TYPESAFE_API_KEY" ] && [ -n "$TYPESAFE_BASE_URL" ] && [ -n "${{ACTIONS_ID_TOKEN_REQUEST_URL:-}}" ]; then
            aud=$(jq -rn --arg a "$TYPESAFE_BASE_URL" '$a|@uri')
            TYPESAFE_API_KEY=$(curl -fsS --max-time 10 "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=$aud" \\
              -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" | jq -r '.value // empty') || TYPESAFE_API_KEY=""
            if [ -n "$TYPESAFE_API_KEY" ]; then echo "::add-mask::$TYPESAFE_API_KEY"; fi
          fi
          export TYPESAFE_API_KEY TYPESAFE_BASE_URL   # this step only
          if [ -z "$TYPESAFE_API_KEY" ] || [ -z "$TYPESAFE_BASE_URL" ] || [ -z "$TYPESAFE_DEFAULT_MODEL" ]; then
            export BRIEF_S1=off
          fi
          uvx --from "brief[s1] @ {BRIEF_SOURCE}" brief triage --amendments --json --base "origin/$BASE" > "$RUNNER_TEMP/out.json"
          # the judged commit rides in the verdict, so a later merge attempt can match it
          jq -c --arg sha "$(git rev-parse HEAD)" '. + {{sha: $sha}}' "$RUNNER_TEMP/out.json" > "$RUNNER_TEMP/triage.json"
          jq -r .summary "$RUNNER_TEMP/triage.json" | tee -a "$GITHUB_STEP_SUMMARY"
          echo "verdict=$(jq -r .verdict "$RUNNER_TEMP/triage.json")" >> "$GITHUB_OUTPUT"
          echo "triage=$(jq -c . "$RUNNER_TEMP/triage.json")" >> "$GITHUB_OUTPUT"
          echo "sha=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"
      - name: keep the verdict for a merge attempt started by another workflow's completion
        uses: actions/upload-artifact@v4
        with:
          name: brief-triage
          path: ${{{{ runner.temp }}}}/triage.json
          retention-days: 30
          overwrite: true
      - name: brief doctor (advisory — latent drift; does not block)
        if: always()   # surface drift even when the gate blocks, for the human PR view
        run: uvx --from {BRIEF_SOURCE} brief doctor --repo .
      - name: brief update check (advisory)
        if: always()
        run: |
          latest=$(git ls-remote --tags --refs {BRIEF_REPO} 'v*' | sed 's|.*refs/tags/||' | grep -E '^v[0-9]+\\.[0-9]+\\.[0-9]+$' | sort -V | tail -1)
          if [ -n "$latest" ] && [ "$latest" != "v{__version__}" ] \\
             && [ "$(printf '%s\\n' v{__version__} "$latest" | sort -V | tail -1)" = "$latest" ]; then
            echo "::notice title=brief $latest is available (this repo pins v{__version__})::Read {BRIEF_REPO}/blob/$latest/UPGRADING.md for what to do, then run: uvx --from git+{BRIEF_REPO}@$latest brief init --ci --with-skills, and commit."
          fi
  escalate:
    # Amendments the model did not clear (or no model): label the PR, open one thread per
    # amendment for a maintainer's /ratify or /reject, and record them as escalated, which
    # blocks the gate until each is answered. Same-repo PRs only (a fork's token is read-only).
    needs: govern
    if: >-
      needs.govern.outputs.verdict == 'escalate' && (github.event_name == 'workflow_dispatch'
      || github.event.pull_request.head.repo.full_name == github.repository)
    runs-on: ubuntu-latest
    permissions:
      actions: write
      contents: write
      issues: write
      pull-requests: write
    concurrency:
      group: brief-verdict-${{{{ github.event.pull_request.number || inputs.pr }}}}
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{{{ github.event.pull_request.head.sha || github.sha }}}}
      - uses: astral-sh/setup-uv@v5
      - env:
          GH_TOKEN: ${{{{ github.token }}}}
          PR: ${{{{ github.event.pull_request.number || inputs.pr }}}}
          TRIAGE: ${{{{ needs.govern.outputs.triage }}}}
        run: |
          gh label create needs-ratification --repo "$GITHUB_REPOSITORY" --color B60205 \\
            --description "brief: a decision change waiting for a human" 2>/dev/null || true
          gh pr edit "$PR" --repo "$GITHUB_REPOSITORY" --add-label needs-ratification
          printf '%s' "$TRIAGE" > "$RUNNER_TEMP/triage.json"
          uvx --from {BRIEF_SOURCE} brief thread escalate --pr "$PR" --triage "$RUNNER_TEMP/triage.json"
  verdict:
    # A maintainer's /ratify or /reject. Every other comment skips this job without a runner.
    if: >-
      (github.event_name == 'pull_request_review_comment'
      || (github.event_name == 'issue_comment' && github.event.issue.pull_request))
      && (startsWith(github.event.comment.body, '/ratify') || startsWith(github.event.comment.body, '/reject'))
    runs-on: ubuntu-latest
    permissions:
      actions: write
      contents: write
      issues: write
      pull-requests: write
    concurrency:
      group: brief-verdict-${{{{ github.event.pull_request.number || github.event.issue.number }}}}
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
        with:
          ref: refs/pull/${{{{ github.event.pull_request.number || github.event.issue.number }}}}/head
      - uses: astral-sh/setup-uv@v5
      - env:
          GH_TOKEN: ${{{{ github.token }}}}
        run: uvx --from {BRIEF_SOURCE} brief thread command --event "$GITHUB_EVENT_PATH"
  automerge:
    # The model ratifies by merging. Runs only when the gate passed and the triage rated EVERY
    # pending amendment auto-ratifiable (one escalated amendment means a human decides). Any
    # code in the PR is merged with the amendment. Skips fork PRs, drafts, a PR labelled
    # local-verified or needs-ratification, a head that moved past the judged commit, and any
    # other check on that commit that failed. It never waits: while another check is still
    # running it exits, and the completion of another workflow on the PR (workflow_run) or of
    # a third-party CI app (check_suite) starts it again. A re-started attempt never asks the
    # model: it merges only the head the latest brief run on it judged auto-ratifiable after
    # the gate passed (that run's brief-triage artifact). Opt out: set the repository variable
    # BRIEF_AUTO_MERGE=off.
    name: brief auto-merge
    needs: govern
    if: >-
      !cancelled() && vars.BRIEF_AUTO_MERGE != 'off'
      && ((needs.govern.result == 'success' && needs.govern.outputs.verdict == 'auto-ratifiable' && (github.event_name == 'workflow_dispatch'
      || (github.event_name == 'pull_request'
      && github.event.pull_request.head.repo.full_name == github.repository && !github.event.pull_request.draft)))
      || (github.event_name == 'workflow_run' && github.event.workflow_run.event == 'pull_request'
      && github.event.workflow_run.conclusion == 'success'
      && github.event.workflow_run.head_repository.full_name == github.repository
      && github.event.workflow_run.pull_requests[0] != null)
      || (github.event_name == 'check_suite' && github.event.check_suite.conclusion == 'success'
      && github.event.check_suite.pull_requests[0] != null))
    runs-on: ubuntu-latest
    permissions:
      actions: read
      checks: read
      contents: write
      pull-requests: write
      statuses: read
    concurrency:
      # one attempt per PR at a time: a second one finds the PR merged, or the head moved
      group: brief-merge-${{{{ github.event.pull_request.number || inputs.pr || github.event.workflow_run.pull_requests[0].number || github.event.check_suite.pull_requests[0].number }}}}
      cancel-in-progress: false
    outputs:
      merged: ${{{{ steps.merge.outputs.merged }}}}
      pr: ${{{{ steps.merge.outputs.pr }}}}
      triage: ${{{{ steps.merge.outputs.triage }}}}
    steps:
      - name: merge the PR on the model's verdict
        id: merge
        env:
          GH_TOKEN: ${{{{ github.token }}}}
          PR: ${{{{ github.event.pull_request.number || inputs.pr || github.event.workflow_run.pull_requests[0].number || github.event.check_suite.pull_requests[0].number }}}}
          SHA: ${{{{ needs.govern.outputs.sha }}}}         # empty when another workflow started this
          TRIAGE: ${{{{ needs.govern.outputs.triage }}}}
          WORKFLOW_REF: ${{{{ github.workflow_ref }}}}
        run: |
          skip() {{ echo "::notice title=brief auto-merge skipped::$1"; echo "brief auto-merge skipped: $1" >> "$GITHUB_STEP_SUMMARY"; exit 0; }}
          [ -n "$PR" ] || skip "no pull request"
          pr=$(gh pr view "$PR" --repo "$GITHUB_REPOSITORY" --json state,isDraft,isCrossRepository,headRefOid,labels) || skip "cannot read PR #$PR"
          [ "$(jq -r .state <<<"$pr")" = OPEN ] || skip "PR #$PR is not open"
          [ "$(jq -r .isCrossRepository <<<"$pr")" = false ] || skip "fork PR: a maintainer merges it"
          [ "$(jq -r .isDraft <<<"$pr")" = false ] || skip "draft PR"
          jq -e '[.labels[].name] | any(. == "local-verified" or . == "needs-ratification")' <<<"$pr" >/dev/null \\
            && skip "labelled local-verified or needs-ratification: a human merges it"
          judged=$GITHUB_RUN_ID
          if [ -z "$SHA" ]; then
            # Started by another workflow: never re-ask the model. The verdict is the triage the
            # latest brief run on the PR head recorded, and only if that run's gate passed.
            SHA=$(jq -r .headRefOid <<<"$pr")
            wf=${{WORKFLOW_REF%@*}}
            judged=$(gh api "repos/$GITHUB_REPOSITORY/actions/workflows/${{wf##*/}}/runs?head_sha=$SHA&per_page=20" \\
              | jq -r '[.workflow_runs[] | select(.event == "pull_request" or .event == "workflow_dispatch")][0].id // empty') \\
              || skip "cannot read the brief runs"
            [ -n "$judged" ] || skip "no brief run judged $SHA"
            gate=$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$judged/jobs" \\
              | jq -r '[.jobs[] | select(.name == "govern")][0].conclusion // "-"') || skip "cannot read run $judged"
            [ "$gate" = success ] || skip "the gate has not passed on $SHA (run $judged: $gate)"
            gh run download "$judged" --repo "$GITHUB_REPOSITORY" --name brief-triage --dir "$RUNNER_TEMP/judged" \\
              || skip "run $judged kept no triage for $SHA"
            TRIAGE=$(cat "$RUNNER_TEMP/judged/triage.json")
          fi
          [ -n "$SHA" ] || skip "no judged commit"
          [ "$(jq -r .headRefOid <<<"$pr")" = "$SHA" ] || skip "the head moved past the judged commit $SHA"
          [ "$(jq -r .verdict <<<"$TRIAGE")" = auto-ratifiable ] && [ "$(jq -r .sha <<<"$TRIAGE")" = "$SHA" ] \\
            || skip "$SHA was not judged auto-ratifiable"
          # Every other check on the judged commit must have passed. This run and the judged
          # brief run are left out (its gate passed, or nothing got here).
          runs=$(gh api --paginate "repos/$GITHUB_REPOSITORY/commits/$SHA/check-runs" \\
            | jq -r --arg self "/actions/runs/$GITHUB_RUN_ID/" --arg judged "/actions/runs/$judged/" \\
              '.check_runs[] | select((.details_url // "") | contains($self) or contains($judged) | not) | [.status, (.conclusion // "-"), .name] | @tsv') \\
            || skip "cannot read the check runs"
          bad=$(awk -F'\\t' '$1 == "completed" && $2 != "success" && $2 != "skipped" && $2 != "neutral" {{print $3}}' <<<"$runs")
          [ -z "$bad" ] || skip "checks not green: $(echo $bad)"
          status=$(gh api "repos/$GITHUB_REPOSITORY/commits/$SHA/status" --jq '"\\(.total_count) \\(.state)"') || skip "cannot read the commit status"
          case "$status" in 0\\ *|*\\ success) ;; *\\ pending) running="commit status" ;; *) skip "commit status is ${{status#* }}" ;; esac
          running=$(echo $(awk -F'\\t' '$1 != "completed" {{print $3}}' <<<"$runs") ${{running:-}})
          if [ -n "$running" ]; then
            echo "::notice title=brief auto-merge not yet::still running on $SHA: $running. The next workflow on the PR to finish retries the merge."
            echo "brief auto-merge not yet: still running on $SHA: $running" >> "$GITHUB_STEP_SUMMARY"
            exit 0
          fi
          gh pr merge "$PR" --repo "$GITHUB_REPOSITORY" --squash --match-head-commit "$SHA" \\
            || {{ echo "::warning title=brief auto-merge failed::merge it by hand (branch protection may require a review)"; exit 0; }}
          echo "merged=true" >> "$GITHUB_OUTPUT"
          echo "pr=$PR" >> "$GITHUB_OUTPUT"
          echo "triage=$(jq -c . <<<"$TRIAGE")" >> "$GITHUB_OUTPUT"
          echo "brief: merged #$PR on the model's verdict" >> "$GITHUB_STEP_SUMMARY"
  ratify:
    # The merge was the ratification; this records it: publish each decision the merge
    # changed and archive its amendment as ratified by the merger, or by the model when the
    # automerge job merged (stamped `s1 <model> p=<a>/<b> (merge of #N)`, `ratified_via:
    # model`; only amendment versions the triage cleared). No loop: a push made with
    # GITHUB_TOKEN starts no workflow (which is also why this job follows automerge), the
    # bot's own pushes are skipped, and a re-run finds nothing pending.
    needs: [govern, automerge]
    if: >-
      !cancelled() && ((github.event_name == 'push' && github.actor != 'github-actions[bot]')
      || needs.automerge.outputs.merged == 'true')
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: read
    concurrency:
      group: brief-ratify
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
        with:
          # the branch tip, so a queued run sees the previous run's commit
          ref: ${{{{ github.event_name == 'push' && github.ref || github.event.repository.default_branch }}}}
      - uses: astral-sh/setup-uv@v5
      - name: ratify merged amendments
        env:
          GH_TOKEN: ${{{{ github.token }}}}
          TRIAGE: ${{{{ needs.automerge.outputs.merged == 'true' && needs.automerge.outputs.triage || '' }}}}
          MERGED_PR: ${{{{ needs.automerge.outputs.pr }}}}
        run: |
          if [ -n "$TRIAGE" ]; then
            printf '%s' "$TRIAGE" > "$RUNNER_TEMP/triage.json"
            by="$(jq -r .stamp "$RUNNER_TEMP/triage.json") (merge of #$MERGED_PR)"
            set -- --triage "$RUNNER_TEMP/triage.json"
          else
            pr=$(gh api "repos/$GITHUB_REPOSITORY/commits/$GITHUB_SHA/pulls" --jq '[.[] | select(.merged_at)][0].number // empty' 2>/dev/null || true)
            if [ -n "$pr" ]; then
              who=$(gh api "repos/$GITHUB_REPOSITORY/pulls/$pr" --jq '.merged_by.login // empty' 2>/dev/null || true)
              by="${{who:-$GITHUB_ACTOR}} (merge of #$pr)"
            else
              by="$GITHUB_ACTOR (push of $GITHUB_SHA)"
            fi
          fi
          uvx --from {BRIEF_SOURCE} brief ratify --pending --push --by "$by" "$@"
"""


def kypp_url(url: str) -> str:
    """`url` as the triage's default TYPESAFE_BASE_URL (and OIDC audience): https, no trailing
    slash, nothing that could break out of the workflow's quoted expression."""
    url = url.strip().rstrip("/")
    if url and not _KYPP_URL_RE.fullmatch(url):
        raise ValueError(f"not an https URL brief can write into the workflow: {url!r}")
    return url


def baked_kypp_url(workflow: str) -> str | None:
    """The kypp URL an existing managed workflow was written with, or None."""
    m = _BAKED_RE.search(workflow)
    return m.group(1) if m else None


def ci_workflow(watch: list[str] | tuple[str, ...] = (), kypp: str = DEFAULT_KYPP_URL) -> str:
    """The CI workflow for a repo whose other pull-request workflows are named `watch`: each
    one's completion re-runs the auto-merge attempt (no runner waits for them). None: no
    `workflow_run` trigger, since the brief run itself is then the last check. `kypp` is the
    triage's default System One URL (a TYPESAFE_BASE_URL repo variable overrides it)."""
    url = kypp_url(kypp)
    wf = CI_TEMPLATE.replace(KYPP_SLOT, f" || '{url}'" if url else "")
    if not watch:
        return wf.replace(WATCH_SLOT, "")
    names = ", ".join(json.dumps(n) for n in watch)
    return wf.replace(WATCH_SLOT, (
        "  workflow_run:           # another PR workflow finished: retry the auto-merge (re-run\n"
        "    # `brief init --ci` after adding or renaming a workflow)\n"
        f"    workflows: [{names}]\n"
        "    types: [completed]\n"))


CI_WORKFLOW = ci_workflow()  # a repo with no other pull-request workflow
