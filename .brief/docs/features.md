---
id: features
type: features
title: brief feature map
---

# brief feature map

What each part of brief is, where its code lives, and what bites there. Address a feature
as `doc://brief/features@latest#<id>`; `brief features <files>` lists the ones a diff
touches. Internal areas are features too. When code moves, update `paths:` in the same
change — `brief check` blocks a glob that matches nothing.

<!-- brief:anchor refs -->
## doc:// refs

```yaml
paths:
  - "src/brief/refs.py"
  - "src/brief/pin.py"
```

Parse and format `doc://<project>/<doc-id>@<rev>#<anchor>`, find refs embedded in code,
and `brief pin` floating aliases to the latest published revision.

### Gotchas
- `pin.py` carries its own ref regex (it also matches `prompt://` and `test://`); a
  change to the ref grammar has to land in both files.
- `pin` leaves `@stable` and unpublished docs alone on purpose.

<!-- brief:anchor docs-resolve -->
## Doc parsing and resolution

```yaml
paths:
  - "src/brief/docs.py"
  - "src/brief/resolve.py"
  - "src/brief/versions.py"
```

Load `.brief/docs` (frontmatter, anchors, body hashes), resolve a ref across revisions,
publish frozen `versions/vNNNN.md` snapshots, and flag stale pins.

### Gotchas
- `load_index` skips any path with a `versions` segment, so a doc can't live under a
  directory named `versions`.
- `@latest` on an unpublished doc falls back to the live file, so it is mutable until
  the first `brief publish`.
- Staleness compares one anchor's body hash, not the doc revision; editing an
  unrelated anchor never stales a pin.

<!-- brief:anchor gate -->
## L0 gate (`brief check`)

```yaml
paths:
  - "src/brief/gate.py"
  - "src/brief/gitutil.py"
```

Separation of powers over a staged diff or a `base..HEAD` range: ratified-edit,
needs-conformance, amendment-required, broken-ref, empty-glob for the feature map,
pending-ratification (a locked edit carrying its amendments; non-blocking on a range or a
staged feature branch, unless escalated and unanswered), amendment-rejected,
untrusted-verdict, and proposal-only (a range adds an amendment but not its decision text).

### Gotchas
- Locked status is read from the baseline tree and `changed_files` uses `--no-renames`;
  both close known ways to reverse a locked decision (brief#1). Don't "simplify" them.
- Sign-off is opt-in (`signoff: required`, brief#9) and scoped by `ref_blocks` to the
  anchors whose `// Context:` block changed; a comment-only change is exempt unless it
  removes a ref.
- Content diffs go through `gitutil._CONTENT` (`--text --no-ext-diff --no-textconv`): a
  `-diff` attribute or a diff driver must not hide lines, or a change reads as comment-only.
- `glob_match` lives in `docs.py` so `gate` and `features` don't import each other.
- `proposal-only` and `ratify_pending` must agree: a merge ratifies only decision text it
  carried, so the gate blocks a PR whose proposal `_pending` doesn't cover. Loosening one
  without the other brings back the merged-but-unratified amendment (huddles-up #105).

<!-- brief:anchor ratify -->
## Ratification

```yaml
paths:
  - "src/brief/ratify.py"
```

The authorized way a locked decision changes: publish a new revision and archive the
amendment stamped `ratified_rev`. `ratify --pending` records a merged amendment PR in CI.

### Gotchas
- The gate only exempts a locked edit that carries the full ratify output (new archive
  entry plus a new version equal to the live doc). A partial hand-made set is blocked.
- `_pending` (gate) and `ratify_pending` must agree on what a merge may ratify: published
  doc, same path, no revision minted in the PR, every changed anchor amended. Change both.
- `ratify_pending` decides "changed" against the latest published revision, not the push
  range, so a queued or re-run CI job is idempotent.
- With `model=` (CI merged the PR on the triage) a never-escalated anchor is ratified only
  if the triage marked its current key `auto`; `--by` must start with the triage's stamp.
  Both CI paths (push and automerge) commit through `ratify_and_push`; don't re-inline git
  in the workflow template.

<!-- brief:anchor amendment-threads -->
## Amendment threads

```yaml
paths:
  - "src/brief/verdicts.py"
  - "src/brief/threads.py"
```

Per-amendment verdicts. CI opens a PR thread for each escalated amendment; a maintainer's
`/ratify` or `/reject` lands as a line in `.brief/RATIFICATIONS`; the gate and
`ratify --pending` read it per anchor, keyed to the amendment version.

### Gotchas
- Trust has two halves: the gate's offline bot-commit check (`verdicts.provenance`) and
  CI's `brief thread verify` against the bot's unedited replies. Git identity alone is
  forgeable; don't drop `verify` from the template.
- `<!-- brief:triage ... -->` (`threads.TRIAGE_RE`) is written by `thread_body` and by the
  automerge job's comment (jq, in `templates.py`) and read by `eval/amend/feedback.py`.
  Change its shape in all three, or graded calls silently stop being collected.
- The key (`amendment_key`) must be computed the same way in triage, the gate, `command`
  and `ratify_pending`: amendment file text + the live anchor's body hash. The anchor is
  the decision's: a feature map often names a feature after the same id, and its Gotchas
  change as code lands. `key_in_tree` once took whichever doc loaded first, so every
  `/ratify` on huddles-up #109 was refused as stale.
- A `/ratify` may sit below a quote of the bot's comment (GitHub's Quote reply): the
  `verdict` job's `if:` uses `contains`, and `parse_command` skips quoted and fenced lines.
- Bot commits set identity via `GIT_AUTHOR_*`/`GIT_COMMITTER_*` env (`bot_identity`), since
  those env vars beat `-c user.*` when the runner sets them.
- A push with GITHUB_TOKEN starts no workflow: `escalate` and `command` dispatch `brief.yml`
  on the head branch so the gate re-runs. Keep `workflow_dispatch` inputs `pr`/`base`.
- `pull_request_review_comment` runs the PR's own copy of the workflow; like the gate, the
  thread jobs trust that the PR didn't edit `brief.yml`.

<!-- brief:anchor doctor -->
## Doctor

```yaml
paths:
  - "src/brief/doctor.py"
```

Advisory, repo-wide lint for drift the gate doesn't block: stale and unpinned refs,
unpublished or unwired active decisions, features with no paths.

### Gotchas
- Advisory by default; only `--strict` exits nonzero. Don't move its checks into the gate.
- `SOURCE_EXT` is duplicated from `scan.py` on purpose so doctor doesn't couple to backfill.

<!-- brief:anchor feature-map -->
## Feature map

```yaml
paths:
  - "src/brief/features.py"
```

Docs with `type: features`: one anchor per feature, each with a fenced yaml `paths:`
block and a Gotchas section. `brief features` maps files to features.

### Gotchas
- Feature `paths` are not `related_code`; a feature map governs nothing, even if marked
  `active`. Decisions belong in decision docs.

<!-- brief:anchor init-convention -->
## Init and the convention

```yaml
paths:
  - "src/brief/init.py"
  - "src/brief/templates.py"
```

`brief init` scaffolds `.brief/`, injects the AGENTS convention, and optionally writes the
CI workflow, a pre-commit hook, and the skills.

### Gotchas
- The CI workflow installs from `git+https://github.com/vu1n/brief@v<version>`, never
  `uvx brief` (an unrelated PyPI package). Bumping the version needs a pushed tag.
- Re-running init replaces the convention from its marker to the next `## ` heading.
- `--with-skills` owns every `brief-*` skill dir: it replaces each whole and deletes ones no
  longer shipped. Never name a user skill `brief-*`.
- Every release needs a `## v<version>` UPGRADING.md entry (Changed/Do); a test enforces it.
- `CI_WORKFLOW` is an f-string: a shell `\` must be written `\\` and `{`/`}` doubled, or a
  line continuation silently vanishes. `tests/test_automerge.py` runs the automerge step's
  shell against a fake `gh`; keep it running when you edit that step.
- The triage step's OIDC audience is `TYPESAFE_BASE_URL` with one trailing slash cut, and
  kypp compares it byte for byte with its `KYPP_PUBLIC_URL`, so the two must be spelled the
  same. `id-token: write` belongs to `govern` only. The step blanks a `TYPESAFE_API_KEY`
  secret unless `REPO_BASE_URL` (the bare repo variable) is set, so a secret never reaches
  the baked default URL. `init` keeps a baked `--kypp-url` across
  re-runs by reading it back from the managed workflow (`baked_kypp_url`); change the
  `TYPESAFE_BASE_URL` env line's shape and that read-back silently drops the URL.
- The `automerge` job must never wait (no sleep loop: it billed a runner for the whole
  wait). Pending checks end it; `workflow_run` (names from `init._pr_workflows`, written by
  `ci_workflow`) and `check_suite` start it again. A re-started attempt has no govern
  outputs: it trusts only the latest brief run on the PR head whose `govern` job passed and
  whose `brief-triage` artifact names that sha, and it must leave that run's own check runs
  out of the green check, or a still-finishing brief run blocks the merge forever.

<!-- brief:anchor backfill -->
## Backfill

```yaml
paths:
  - "src/brief/scan.py"
  - "skills/brief-backfill/**"
```

`brief backfill` scans docs, code signals and modules into a context map; the skill
reconstructs the decision layer from it.

<!-- brief:anchor skills -->
## Skills

```yaml
paths:
  - "skills/**"
```

The behavior layer agents run: author a decision, amend, review, backfill, seed a
feature map.

### Gotchas
- Skills are slash-only (`disable-model-invocation: true`, brief#4); keep new ones that way.
- The wheel ships them via `force-include` as `brief/_skills`.

<!-- brief:anchor cli -->
## CLI

```yaml
paths:
  - "src/brief/cli.py"
```

Thin Typer entrypoint over the primitives.

### Gotchas
- Keep it to deterministic primitives; workflow and judgment go in the convention and skills.

<!-- brief:anchor system-one -->
## System One triage

```yaml
paths:
  - "src/brief/s1.py"
  - "src/brief/triage.py"
  - "eval/s1/**"
```

Optional client for System One decision models over the TypeSafe API (`brief[s1]`;
Jev, Clef, any compatible endpoint): typed questions in, calibrated probabilities out. Used to triage what
reaches a human or agent. `brief triage` writes tagged `conforms` lines for the
sign-off asks it rates below `THRESHOLD`; `eval/s1/` is where that threshold comes from.
`brief triage --amendments` rates pending amendments for reversal and impact.

### Gotchas
- `decide` returns None (or drops an answer) on any failure; callers must read that as
  "no opinion" and fall back to the mechanical rule, never as "no".
- Out-of-range, non-finite, or wrong-type answers are dropped in `s1._answer`/`noul_p`:
  a confidence is not P(no), and -0.5 must not read as a confident "no".
- Amendment triage selects the code diff by the decision's globs at the baseline *and* in
  the PR: a narrowed `related_code` must not hide the code it un-governs from the model.
- Amendment triage fails closed: no model, an error, or a missing/invalid answer escalates.
- A cutoff belongs to one model and one question. `REVIEW_THRESHOLD` was tuned on Clef by
  `eval/cutoff.py` from saved `eval/amend` scores and a stated miss cost; re-run both before
  changing the model, the question or the cutoff. The lowest should-see score is not a
  safe cutoff by itself: with two cases in the tail, a rule that learns it leaks held out.
- The gate matches `conforms` on the bare anchor id across docs, so triage clears an id only
  when every ask sharing it is under the threshold; staged mode writes only its own lines
  to the index (`gitutil.stage_content`), never `git add` of the whole SIGNOFF.
- It may remove asks, rank queues, and rate amendments (`auto-ratifiable` / `escalate`).
  Never let it block or pass the gate: the gate must stay deterministic and keyless in
  every consuming repo's CI. The CI template's `automerge` job merges an all-auto-ratifiable
  PR (the owner chose this, 2026-10-11): the model's thresholds now decide what merges
  without a person, so raise them only with an eval. An anchor escalated on the PR stays
  escalated (`AmendmentVerdict.escalated`), or rewording would launder a held amendment.

<!-- brief:anchor evidence -->
## Amendment evidence

```yaml
paths:
  - "src/brief/evidence.py"
  - "eval/evidence/**"
```

`brief evidence`: what a reviewer needs for each pending amendment, with sources. Exact
changed lines and qualifiers, the amendment's sections, governed scope before/after, and
decisions linked by refs or shared files; optionally Clef's shadow "may undermine" links.

### Gotchas
- Advisory only: the gate, triage, `ratify` and `threads` must never import it (a test
  checks). Don't feed its links or scores into a verdict, a threshold or a label.
- A missing model answer is "not checked", never "no impact"; model-only links stay
  labeled as inferred and are never written into a decision's refs.
- Scope is compared at the merge-base: a narrowing shows the files that leave governance
  and which of them the PR edits. Amendment triage reads code under both sets of globs.
- `MODEL_SHOW`/`MODEL_TOP` come from `eval/evidence` (14 cases chosen and labeled by one
  author); treat them as development settings.

<!-- brief:anchor eval -->
## Eval

```yaml
paths:
  - "eval/**"
```

The memory vs in-repo docs vs Brief experiment (brief#2) and its results.
