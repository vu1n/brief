# Upgrading brief

Read this when the `brief` CI notice says a newer version exists. Read every entry newer than
the version your repo pins (`.github/workflows/brief.yml`), oldest first. Each entry has two
parts. **Changed** says what behaves differently. **Do** is what the upgrading agent must do,
or "nothing".

The upgrade itself is always the same: run
`uvx --from git+https://github.com/vu1n/brief@<new tag> brief init --ci --with-skills`,
do every **Do** step below, run `brief check` and `brief doctor`, and commit everything in
one PR.

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
