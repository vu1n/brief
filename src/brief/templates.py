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

Decisions are **ratified constraints, not editable notes**. Develop *to* them:

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
  needs human ratification before code can land. The amendment PR may also carry the
  proposed decision text (one amendment per anchor it changes); a human merging that PR is
  the ratification. If CI escalates an amendment, it opens a PR thread for it: answer
  questions there, never `/ratify` it yourself, and never edit `.brief/RATIFICATIONS`. On
  `/reject`, revise the amendment to meet the reason, or withdraw it. Never bypass the
  commit hook.
- At each site that embodies a decision, leave a one-line comment:
  `// Context: doc://<project>/<doc-id>@latest#<anchor> — <the rule, in one line>`.
  The ref makes it checkable; the one-line rule puts the constraint in front of the next
  agent exactly where it touches the code. Keep the full reasoning in the decision doc.
- If your memory, notes, or habits disagree with an active decision, the decision wins:
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

from . import __version__

# Installed from a pinned tag, never from PyPI: `brief` on PyPI is an unrelated package, and
# an unpinned source would let any push to brief's main change every governed repo's gate.
BRIEF_REPO = "https://github.com/vu1n/brief"
BRIEF_SOURCE = f"git+{BRIEF_REPO}@v{__version__}"
CI_MARKER = "# Managed by `brief init --ci`: re-running it rewrites this file. Delete this line to own it."

CI_WORKFLOW = f"""\
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
  workflow_dispatch:      # the bot's verdict commits start no run, so it dispatches one
    inputs:
      pr:
        required: true
      base:
        required: true
jobs:
  govern:
    if: github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: read
    env:
      BASE: ${{{{ github.base_ref || inputs.base }}}}
      PR: ${{{{ github.event.pull_request.number || inputs.pr }}}}
    outputs:
      verdict: ${{{{ steps.triage.outputs.verdict }}}}
      triage: ${{{{ steps.triage.outputs.triage }}}}
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
        # TYPESAFE_BASE_URL. Unset (or a fork PR, which gets no secrets) = escalate.
        env:
          TYPESAFE_API_KEY: ${{{{ secrets.TYPESAFE_API_KEY }}}}
          TYPESAFE_BASE_URL: ${{{{ vars.TYPESAFE_BASE_URL }}}}
          TYPESAFE_DEFAULT_MODEL: ${{{{ vars.TYPESAFE_DEFAULT_MODEL }}}}
        run: |
          if [ -z "$TYPESAFE_API_KEY" ] || [ -z "$TYPESAFE_BASE_URL" ] || [ -z "$TYPESAFE_DEFAULT_MODEL" ]; then
            export BRIEF_S1=off
          fi
          uvx --from "brief[s1] @ {BRIEF_SOURCE}" brief triage --amendments --json --base "origin/$BASE" > "$RUNNER_TEMP/triage.json"
          jq -r .summary "$RUNNER_TEMP/triage.json" | tee -a "$GITHUB_STEP_SUMMARY"
          echo "verdict=$(jq -r .verdict "$RUNNER_TEMP/triage.json")" >> "$GITHUB_OUTPUT"
          echo "triage=$(jq -c . "$RUNNER_TEMP/triage.json")" >> "$GITHUB_OUTPUT"
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
  ratify:
    # The merge was the ratification; this records it: publish each decision the merge
    # changed and archive its amendment as ratified by the merger. No loop: a push made with
    # GITHUB_TOKEN starts no workflow, the bot's own pushes are skipped, and a re-run finds
    # nothing pending.
    if: github.event_name == 'push' && github.actor != 'github-actions[bot]'
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
          ref: ${{{{ github.ref }}}}   # the branch tip, so a queued run sees the previous run's commit
      - uses: astral-sh/setup-uv@v5
      - name: ratify merged amendments
        env:
          GH_TOKEN: ${{{{ github.token }}}}
        run: |
          pr=$(gh api "repos/$GITHUB_REPOSITORY/commits/$GITHUB_SHA/pulls" --jq '[.[] | select(.merged_at)][0].number // empty' 2>/dev/null || true)
          if [ -n "$pr" ]; then
            who=$(gh api "repos/$GITHUB_REPOSITORY/pulls/$pr" --jq '.merged_by.login // empty' 2>/dev/null || true)
            by="${{who:-$GITHUB_ACTOR}} (merge of #$pr)"
          else
            by="$GITHUB_ACTOR (push of $GITHUB_SHA)"
          fi
          uvx --from {BRIEF_SOURCE} brief ratify --pending --by "$by"
          if [ -z "$(git status --porcelain -- .brief)" ]; then exit 0; fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add .brief
          git commit -qm "brief: ratify amendments ($by)"
          git push
"""
