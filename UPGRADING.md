# Upgrading brief

Read this when the `brief` CI notice says a newer version exists. Read every entry newer than
the version your repo pins (`.github/workflows/brief.yml`), oldest first. Each entry has two
parts. **Changed** says what behaves differently. **Do** is what the upgrading agent must do,
or "nothing".

The upgrade itself is always the same: run
`uvx --from git+https://github.com/vu1n/brief@<new tag> brief init --ci --with-skills`,
do every **Do** step below, run `brief check` and `brief doctor`, and commit everything in
one PR.

## v0.5.1

- **Changed:** CI triage needs no secret. The `govern` job gains `permissions: id-token:
  write`, and its triage step, when the repo has no `TYPESAFE_API_KEY` secret, fetches a
  GitHub Actions OIDC token whose audience is `TYPESAFE_BASE_URL` (trailing slash removed)
  and sends it as the bearer, for that step only. `TYPESAFE_DEFAULT_MODEL` now defaults to
  `clef`, and `TYPESAFE_BASE_URL` to the kypp Worker URL written into the workflow by
  `brief init --ci --kypp-url https://<worker>` (a re-run without the flag keeps the URL
  already there). brief pins no public kypp URL, so without the flag or a
  `TYPESAFE_BASE_URL` repo variable there is still no model and every amendment escalates.
  Repo variables override both defaults, and a `TYPESAFE_API_KEY` secret wins over OIDC.
  Failure is closed as before: no URL, no token, a refused token or any model error
  escalates. **Fork PRs get no OIDC token** (and no secrets), so their amendments always
  escalate.
- **Do:** re-run `brief init --ci --kypp-url https://<your kypp worker>` (or set the
  `TYPESAFE_BASE_URL` repo variable). On the Worker, list your GitHub owner in
  `KYPP_OIDC_OWNERS` and make sure its `KYPP_PUBLIC_URL` is exactly the URL you gave, since
  that is the token's audience. Then delete the `TYPESAFE_API_KEY` secret and the
  `TYPESAFE_DEFAULT_MODEL` variable if they only pointed at kypp; keep them to use
  another TypeSafe endpoint. With `--kypp-url`, a repo that has the secret but no
  `TYPESAFE_BASE_URL` variable sends that secret to the kypp URL: set the variable too.

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
