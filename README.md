# brief

**Doc-driven development as a governance system.** Architectural decisions become
versioned, addressable, and *read-only to the coding loop* — so your design docs stay
true instead of rotting.

## The idea

In normal development, code is the source of truth and docs lag it — so docs drift
*invisibly*: nothing breaks when a doc is wrong. `brief` inverts that:

- **Decisions are authoritative state**, written as governance docs in `.brief/docs/`.
- **Code conforms to decisions** and references them by a stable handle:
  `doc://<project>/<doc-id>@<rev>#<anchor>`.
- **A decision is read-only to coding work.** An agent (or human) can't quietly rewrite a
  decision to make a change fit. To change one, you propose an **amendment** and a human
  **ratifies** it — *separation of powers: the party being checked can't edit the check.*

Drift stops being "docs silently diverged from code" (undetectable) and becomes "code
diverged from spec" — which is testable.

## Does it actually work?

We tested it adversarially before building most of it. On a real Rust codebase (8 real
architectural decisions), coding agents were given tasks that **contradicted firm
decisions**, and we measured whether they'd quietly rewrite the decision to ratify their
own code:

- Naive "docs are editable truth" framing → agents reversed the decision **4 / 4 times**.
- Separation-of-powers framing (decisions read-only) → **0 reversals**; every agent stopped
  and filed an amendment — including on a weaker model (**0 / 8 reversals across two model
  tiers**).

The convention does the persuading; the gate + CI are the backstop.

A reproducible follow-up lives in [`eval/`](eval/): 294 graded runs on two model tiers,
comparing stale agent memory, plain in-repo docs and brief
([results](eval/RESULTS.md)). Findings:
- Stale memory took the weaker model from 14/18 to 4/18.
- A one-line rule at the code plus a decisions doc restored 15–18/18.
- On a conflicting task, plain docs were rewritten to fit the change: Haiku 9/9, and Sonnet
  3/3 under "keep docs up to date" framing. Brief decisions were rewritten 0/12, and the gate
  blocked every forbidden change.

## Install

```sh
uv tool install git+https://github.com/vu1n/brief@v0.5.1   # not on PyPI; `brief` there is unrelated
brief --help
```

Releases are cut by bumping `version` in `pyproject.toml` and `src/brief/__init__.py`: on
merge to main, `release.yml` tags `v<version>` and publishes a GitHub release. Every
release adds an entry to [UPGRADING.md](UPGRADING.md): what changed for a governed repo and
what the upgrading agent must do (a test fails without it). Repos set up
with `brief init --ci` get a PR notice when a newer tag exists, with the one command that
upgrades them.

## Quickstart

```sh
brief init --with-skills              # scaffold .brief/, inject the convention, install skills
# author a decision in .brief/docs/<id>.md (frontmatter + <!-- brief:anchor --> + the invariant)
brief publish my-decision             # freeze revision v0001
# reference it from code:   // Context: doc://<project>/my-decision@latest#<anchor>
brief check                           # run before committing (CI runs the same on PRs)
brief pin                             # freeze @latest -> @0001 in your staged code
```

The skills ship with `disable-model-invocation: true`: "brief" is a generic word, and a
globally installed skill with an auto-matching description pulls unrelated agents into
governance work in repos that never adopted brief. Run them as `/brief-amend`,
`/brief-author-decision`, `/brief-backfill`, `/brief-review`. The gate, not description
matching, is what routes an agent to an amendment.

When a task can't be done without changing a ratified decision:

```sh
# write .brief/amendments/<anchor>.md + "<anchor> amend-proposed: ..." in .brief/SIGNOFF,
# optionally put the proposed decision text in the same PR, then STOP
# merging the PR ratifies it: CI runs `brief ratify --pending` and commits the new revision
brief ratify <anchor> --by you        # without CI: a human edits the decision, then ratifies by hand
```

On the PR the gate reports the edit as `pending-ratification` (it does not block); an edit
to a locked decision without its amendment is still blocked. With a System One model
configured, CI rates each amendment for reversal and impact and labels the PR
`needs-ratification` unless both are low. When every amendment on the PR is low on both and
every other check is green, CI merges the PR itself, code included, and the archive records
the model as the ratifier (`ratified_via: model`). Set the repo variable
`BRIEF_AUTO_MERGE=off` to keep every merge a human's.

The model needs no secret when it is a kypp Worker: `brief init --ci` writes
`https://kypp.vu1n.dev` into the workflow (`--kypp-url https://<worker>` picks another), and the
triage step sends the job's GitHub Actions OIDC token (audience: that URL) to Clef there.
The Worker must list your GitHub owner in `KYPP_OIDC_OWNERS`. Repo variables
`TYPESAFE_BASE_URL` and `TYPESAFE_DEFAULT_MODEL` (default `clef`) override it, and a
`TYPESAFE_API_KEY` secret is sent instead of the OIDC token, but only to a
`TYPESAFE_BASE_URL` the repo sets itself. Fork PRs get no token, so their amendments escalate.

An escalated amendment also gets its own review thread on `.brief/amendments/<anchor>.md`.
A maintainer replies `/ratify` or `/reject <reason>` there (or comments `/ratify <anchor>`
on the PR); the agent can answer questions in the thread but can't ratify. CI records each
verdict in `.brief/RATIFICATIONS`, and the gate blocks the PR while any escalated amendment
is unanswered or rejected. A rejected amendment goes back to the agent: revising it makes a
new version that comes back to the thread. Merging publishes only what was ratified.

## The governance stack

| Layer | What | Where it lives |
|-------|------|----------------|
| **L0** | mechanical gate: decisions read-only; conformance asserted | `brief check` (local self-check + CI) |
| **L1** | independent verifier audits a conformance claim or amendment | the `brief-review` skill (spawns a fresh agent) |
| **L2** | conformance tests enforce testable invariants | your project's own tests (`test://`) |
| **L3** | merging the amendment PR ratifies it | PR merge + `brief ratify --pending` in CI |

Only L0 must be code; only CI must enforce it. The heavy lifting is the **behavior layer**:
the always-on convention (`brief init` injects it into your `AGENTS.md`) plus on-demand
skills. `brief` itself is a few deterministic primitives an agent calls, not an app a human
operates.

## CLI

- `brief resolve <ref>` — ref → file, anchor, lines, body, hash (+ stale flag)
- `brief check [--base <ref>]` — the L0 gate (staged locally; a commit range in CI)
- `brief doctor [--strict]` — advisory lint: latent drift the gate *doesn't* block — an active decision that was never published, a governed file with no back-ref, a floating `@latest`, a stale pin. Agents run it and close what it flags; `--strict` fails CI on warnings.
- `brief triage --amendments [--json]` — rate each pending amendment (reverses/weakens? high-impact?): `auto-ratifiable` or `escalate`; writes nothing; no model = escalate
- `brief triage [--base <ref>]` — optional (`brief[s1]` + `TYPESAFE_API_KEY`): a System One model rates each sign-off ask; below p=0.1 it writes the `conforms` line itself, tagged with the score. It sends the decision text and the governed files' diff to `TYPESAFE_BASE_URL`, so only enable it where that is acceptable. The gate never calls the model. See `eval/s1/`.
- `brief pin [files]` — freeze `@latest`/`@current` code refs to a concrete revision
- `brief publish <doc-id>` — mint the next immutable revision
- `brief ratify <anchor>` / `brief ratify --pending` — accept an amendment → new revision, archive the proposal (`--pending`: every amendment whose decision the tree already changed; CI runs it after a merge)
- `brief thread escalate|command|verify` — CI only: open amendment threads, record a `/ratify` or `/reject`, check each recorded verdict against the bot's own reply
- `brief init` — scaffold + inject the convention (`--with-skills`, `--ci`, `--hook`)
- `brief features [files]` — the feature map: each feature's ref and `paths:` globs, or only the features those files touch (see below)
- `brief backfill` — scan code + docs + comments into a context map for reconstructing the decision layer (pairs with the `brief-backfill` skill)

## Feature map

Decisions say what must stay true; a **feature map** says what each part of the codebase
*is*, where its code lives, and what bites there. It is one doc with `type: features`
(by convention `.brief/docs/features.md`), one anchor per feature — user-facing or
internal — so a feature is addressable as `doc://<project>/features@latest#<id>`:

````markdown
<!-- brief:anchor search -->
## Search

```yaml
paths:
  - "src/search/**"
  - "cli/commands/search.ts"
```

What search is, in a paragraph.

### Gotchas
- Results are debounced; wait for the list, not a fixed sleep.
````

`brief features <files>` maps a diff to the features it touches, so an agent reads those
Gotchas before changing the code. `brief check` blocks any `paths:` glob that matches no
tracked file: moving code without updating the map fails instead of silently dropping it.
A feature map governs nothing (its `paths` are not `related_code`) and needs no
ratification to edit. The `brief-feature-map` skill seeds one; brief's own is
[`.brief/docs/features.md`](.brief/docs/features.md).

## Status

MVP. **Built + validated:** resolver, separation-of-powers gate, CI enforcement, behavior
layer (convention + skills), revisions/publish, stale-by-hash, the amendment↔ratify loop,
pin. **Deferred until proven needed:** `pack`, full-text `search`/`index`, a generated human
`site`. Design of record: [`docs/DESIGN.md`](docs/DESIGN.md). Agent/contributor guide:
[`AGENTS.md`](AGENTS.md).

## Move a project onto brief

Paste [`docs/setup-prompt.md`](docs/setup-prompt.md) into your coding agent from the root of
the repo you want to govern. It works for a fresh repo and for one with existing ADRs or a
decisions log, which it migrates instead of duplicating. It captures decisions, wires them
into the code, checks its own work with `brief check` and `brief doctor`, and opens a PR,
and your review of that PR is the ratification.
