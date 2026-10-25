# Upgrading brief

Read this when the `brief` CI notice says a newer version exists. Read every entry newer than
the version your repo pins (`.github/workflows/brief.yml`), oldest first. Each entry has two
parts. **Changed** says what behaves differently. **Do** is what the upgrading agent must do,
or "nothing".

The upgrade itself is always the same: run
`uvx --from git+https://github.com/vu1n/brief@<new tag> brief init --ci --with-skills`,
do every **Do** step below, run `brief check` and `brief doctor`, and commit everything in
one PR.

## v0.5.4

- **Changed:** a maintainer's `/ratify` records on the first try. The version check
  computed the key from the feature map's section when the map names a feature after the
  amendment's anchor (as huddles-up's does), so every `/ratify` was refused as "the
  amendment changed since this thread showed version …". A `/ratify` or `/reject` below a
  quote of the bot's comment (GitHub's Quote reply) now counts too; before, the verdict job
  never started and the comment got no answer.
- **Do:** re-run `brief init --ci` so the verdict job starts for quoted commands. An
  amendment refused as stale before the upgrade needs its `/ratify` posted again.

## v0.5.3

- **Changed:** merging an amendment PR now always ratifies it. The gate blocks a PR that
  adds or edits `.brief/amendments/<anchor>.md` without editing that anchor in the live
  decision (`proposal-only`), because CI's ratify job only publishes decision text the
  merge carried; a proposal merged alone left a person to run `brief ratify` by hand.
  Locally, `brief check` on a feature branch reports a decision edit with its amendment as
  pending instead of blocking the commit, so an agent can commit the proposed text. On the
  default branch, a detached HEAD, or a clone without `origin/HEAD` (brief can't tell
  which branch is the default) it still blocks.
- **Do:** re-run `brief init --ci` so CI pins this version, and re-inject the convention
  (`brief init`) so it says the amendment PR must carry the decision text. If the repo's
  workflow predates the ratify job (no `push` trigger), this is also what adds it: the job
  needs `contents: write` to commit the published revision to the default branch. A live
  proposal from before the upgrade that has no decision text needs it added in its own PR.

- **Changed:** amendment triage auto-ratifies below 0.25, down from 0.3. The cutoff is now
  chosen by `eval/cutoff.py` from what a mistake costs (one should-see amendment merged
  unseen = 20 needless reviews), cross-validated, instead of read off the lowest should-see
  score. On `eval/amend`, Clef clears 15 of 35 harmless amendments instead of 18. When the
  model that answered isn't the one the cutoff was tuned on (Clef), the triage's `why`
  says so.
- **Changed:** every triage call shown to a person can be graded. The escalation thread asks
  the owner to react 👍 (worth their eyes) or 👎 (could have merged on its own), and the
  automerge job now comments on each PR it merges asking 👍 (fine) or 👎 (should have been
  shown). Both comments carry a `<!-- brief:triage ... -->` marker with the score, and
  `eval/amend/feedback.py` collects the graded calls as labeled cases for `eval/cutoff.py`.
- **Do:** re-run `brief init --ci` so the automerge job posts its comment.

## v0.5.2

- **Changed:** the convention block scopes decisions to code. Decisions bind the code an
  agent writes, not the questions it is asked: when exploring or evaluating an option, an
  agent treats decisions as context, says where the option beats the current design, and
  names the decisions it would reverse, instead of ruling it out because a decision exists.
  A decision is framed as a record that may have been wrong or overtaken, not a fixed truth.
  Code still conforms, but an agent that needs workarounds to conform says the decision may
  be out of date instead of coding around it.
  The read-only rule, sign-offs and amendments are unchanged.
- **Changed:** amendment triage asks the model one question, "should this change wait for the
  owner's eyes before it merges?", and auto-ratifies below 0.3, in place of the reversal and
  impact pair at 0.05. The old pair escalated every amendment in pillbox and kypp's history,
  even ones that only added `signoff: required`. On `eval/amend`, Clef now clears 18 of 35
  harmless amendments and none of 58 that need a person. The triage JSON and thread comments
  carry `review` instead of `fiat`/`impact`, and the model stamp is `s1 <model> p=<p>`.
- **Do:** re-run `brief init --ci --with-skills` to refresh the convention block. If the
  repo's own agent docs say decisions are "not re-litigated" or always win, scope that line
  to code changes too.

## v0.5.1

- **Changed:** CI triage needs no secret. The `govern` job gains `permissions: id-token:
  write`, and its triage step, when the repo has no `TYPESAFE_API_KEY` secret, fetches a
  GitHub Actions OIDC token whose audience is `TYPESAFE_BASE_URL` (trailing slash removed)
  and sends it as the bearer, for that step only. `TYPESAFE_DEFAULT_MODEL` now defaults to
  `clef`, and `TYPESAFE_BASE_URL` to the kypp Worker URL written into the workflow by
  `brief init --ci`: `https://kypp.vu1n.dev` unless `--kypp-url https://<worker>` names
  another (a re-run without the flag keeps the URL already there; `--kypp-url ""` writes
  none). Repo variables override both defaults. A `TYPESAFE_API_KEY` secret wins over OIDC,
  but only when the repo also sets `TYPESAFE_BASE_URL`: a secret is never sent to the
  written-in kypp URL.
  Failure is closed as before: no URL, no token, a refused token or any model error
  escalates. **Fork PRs get no OIDC token** (and no secrets), so their amendments always
  escalate.
- **Do:** re-run `brief init --ci` (add `--kypp-url https://<your kypp worker>` for your
  own Worker). On the Worker, list your GitHub owner in `KYPP_OIDC_OWNERS` and make sure
  its `KYPP_PUBLIC_URL` is exactly the workflow's URL, since that is the token's audience.
  Then delete the `TYPESAFE_API_KEY` secret, the `TYPESAFE_BASE_URL` variable and the
  `TYPESAFE_DEFAULT_MODEL` variable if they only pointed at kypp; keep all three to use
  another TypeSafe endpoint.

## v0.5.0

- **Changed:** merging an amendment PR is the ratification. A PR that edits a locked
  decision and carries `.brief/amendments/<anchor>.md` for every anchor it changes is
  reported as `pending-ratification` and does not block (a bare edit is still
  `ratified-edit`; staged commits still block). The CI workflow gains a `push` to `main`
  job that runs `brief ratify --pending` after a merge and commits the new revision as
  `github-actions[bot]`, stamped `ratified_by: <merger> (merge of #N)`. With a
  `TYPESAFE_API_KEY` secret plus `TYPESAFE_BASE_URL` and `TYPESAFE_DEFAULT_MODEL` repo
  variables, each such PR is rated `auto-ratifiable` or labeled `needs-ratification`;
  without them every one is labeled.
  An escalated amendment also gets its own PR review thread: a maintainer replies `/ratify`
  or `/reject <reason>` (or comments `/ratify <anchor>` on the PR), CI records the verdict
  in `.brief/RATIFICATIONS` on the PR branch, and the gate blocks the PR while any
  escalated amendment is unanswered (`pending-ratification`) or rejected
  (`amendment-rejected`). `ratify --pending` publishes a doc only when every escalated
  anchor in it is ratified. A `RATIFICATIONS` line the bot didn't commit is
  `untrusted-verdict`. The workflow gains `pull_request_review_comment`, `issue_comment` and
  `workflow_dispatch` triggers and a `verdict` job.
  **CI merges auto-ratifiable PRs itself.** When the triage rates every amendment on a PR
  `auto-ratifiable` (one escalated amendment leaves the PR to a human), the gate passes,
  and every other check and status on the judged commit is green, the new `automerge` job
  squash-merges the PR with GITHUB_TOKEN. It never waits on a runner: while another check
  is still running it exits, and the next of your PR workflows to finish (`workflow_run`)
  or a third-party CI app's check suite (`check_suite`) starts it again; that attempt reads
  the verdict back from the brief run that judged the head (its `brief-triage` artifact),
  never re-asking the model. **Code in the
  same PR is merged too**, on the model's verdict plus your other checks. Fork PRs, drafts,
  and PRs labelled `local-verified` or `needs-ratification` are skipped. The `ratify` job
  then records the merge with the model as ratifier: `ratified_by: s1 <model> p=<a>/<b>
  (merge of #N)` and a new `ratified_via: model` line (person-made ones say
  `ratified_via: human`). An amendment escalated on a PR stays escalated through its
  revisions on that PR. `brief ratify --pending` gains `--triage` and `--push`.
- **Do:** re-run `brief init --ci`. If `main` is protected, let `github-actions[bot]` push
  to it (or the ratify job fails and the merged decision stays unpublished until someone
  runs `brief ratify --pending` by hand). If your default branch is not `main`, edit the
  `push` branch in `brief.yml` and drop the managed marker. If PR branches are protected,
  let `github-actions[bot]` push to them too (it commits the verdict lines there). If you
  require the `govern` check, nothing else: CI re-dispatches it after each verdict commit.
  `init --ci` lists your other pull-request workflows by name under `workflow_run`; re-run
  it after adding or renaming one (or edit the list), or a PR whose last check is that
  workflow waits for a human. A last check that is a legacy commit status (not a check run)
  starts no retry either. Decide on auto-merge: to keep every merge a human's, set the repository variable
  `BRIEF_AUTO_MERGE=off`. Otherwise, if branch protection requires an approving review, the
  bot's merge fails (the job warns and a human merges as before); allow
  `github-actions[bot]` to merge, or accept that. Without the TypeSafe secret and variables
  nothing is ever auto-ratifiable, so nothing auto-merges.

## v0.4.2

- **Changed:** `brief check` warns when your local brief differs from the version CI pins.
  `init --with-skills` now replaces each `brief-*` skill whole, and removes `brief-*`
  skills brief no longer ships. The CI upgrade notice links to this file.
- **Do:** nothing.

## v0.4.1

- **Changed:** the gate now reads governed changes with `--text --no-ext-diff
  --no-textconv`. A file marked `-diff` or binary, or one with a diff driver, used to
  hide its lines and pass as comment-only. Those changes now raise their sign-off ask.
  `brief triage` fails closed on malformed model answers.
- **Do:** nothing. If a PR that used to pass now gets a sign-off ask on a `-diff` file,
  the ask is correct.

## v0.4.0

- **Changed:** new optional `brief triage`, which needs `brief[s1]` and `TYPESAFE_API_KEY`.
  It writes tagged `conforms` lines for sign-off asks a System One model clears.
  It sends the decision text and the diff to `TYPESAFE_BASE_URL`.
- **Do:** nothing. Only enable triage where sending code to that endpoint is acceptable.

## v0.3.0

- **Changed:** sign-off is opt-in per decision. Only decisions with `signoff: required` in
  their frontmatter ask for a `conforms` line, and only when a change touches the code
  under one of their `// Context:` comments. **After this upgrade, decisions without the
  field stop asking for sign-off.** All active decisions stay read-only either way.
- **Do:** this step needs judgment. List the active decisions
  (`grep -l "status: active" .brief/docs/*.md`). Mark `signoff: required` only on the few
  where silent drift is dangerous: security boundaries, data loss, money. That edits
  ratified decisions, so propose it as an amendment for a human to ratify rather than
  editing the docs directly. Say in the PR which decisions you proposed, and why.

## v0.2.x

- **Changed:** the CI workflow is managed (`# Managed by brief init --ci` marker). The gate
  fails closed on unparseable decision YAML.
- **Do:** nothing. A `brief.yml` without the marker is hand-managed, so bump its tag by hand.
