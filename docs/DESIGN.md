# brief — Doc-Driven Development as a Governance System (Design v0.3)

## Thesis

Agents are now the primary authors and readers of code. In normal development,
**code is the truth and docs lag it** — which is why docs drift *invisibly*:
nothing breaks when a doc is wrong. `brief` inverts this. **Docs are the
authoritative state; code is the derived artifact verified against them.** You
develop *to* the docs. That turns drift from "docs silently diverged from code"
(undetectable) into "code diverged from spec" (testable). The state lives where
the guardrails are, so governance is built-in: you can't develop without touching
the state, the way you can't merge without passing CI.

A `doc://` ref in code is a durable, resolvable handle to a decision. It does not
*guarantee truth* — resolution proves existence, not correctness. Truth is held by
the governance stack (below), not by the ref. We make no "cannot lie" claim.

## Core model

- Markdown = authoritative state (the spec/decisions we develop to)
- git = source of truth for history + provenance queries (`-S`, blame); the vault is a git repo
- `versions/` files = **derived, regenerable materialization of git** — a cache so non-git tools (rg, Obsidian, the indexer, the site) read snapshots without git plumbing
- SQLite = derived, rebuildable index (search / pack / relations only)
- `doc://<project>/<doc-id>@<rev|alias>#<anchor>` = address (scheme tool-agnostic on purpose)
- `brief` = resolver / packer / governance gate
- two generated projections of one graph: `brief pack` (agent view), `brief site` (human view)

## Decisions ledger

| # | Decision |
|---|----------|
| 1 | **Docs = authoritative state**, code is derived/verified. Develop *to* docs. Drift becomes testable ("code diverged from spec"), not invisible. |
| 2 | git = source of truth for history; `versions/` files are a **derived cache** for non-git tools; SQLite = derived index; `doc://` = address; `brief` = resolver/packer/gate. |
| 3 | **Explicit anchors only** (`<!-- brief:anchor id -->`) as governance. Lint *suggests* anchors, never auto-creates. |
| 4 | **Version id = zero-padded monotonic per-doc revision** (`v0005.md`), NOT semver. semver's structure exists for dependency-range resolution, which brief does not have. Revisions sort cleanly in file search; index handles richer queries. |
| 5 | **Significance is computed, not encoded.** "How much changed" is derived from anchor-body-hash diffs at diff/stale time and shown at anchor granularity. It is never a stored, hand-assigned magnitude. |
| 6 | **Split version from lineage.** Code change → lineage entry always; new doc revision only on doc *content* change. |
| 7 | Code refs use `@latest` while working → `brief pin` rewrites to concrete revision on commit → gate blocks broken/unpinned refs in committed code. |
| 8 | **Stale detection trusts anchor body hashes**, not version magnitude. A new doc revision flags a pinned ref stale only if *that anchor's* hash actually moved. |
| 9 | `resolve`/`read` = **filesystem** (reads the materialized cache; always correct, git-backed integrity); index serves search/pack/relations only. |
| 10 | The live doc is `<doc-id>.md` (no `current.md` sidecar). `brief publish` tags git + materializes a frozen `versions/vNNNN.md`; `brief materialize` rebuilds them from tags. |
| 11 | **Governance is defense-in-depth (L0–L3)**, not agent goodwill. The pilot showed the dangerous defection is *reversal-by-fiat* (rewriting a decision to ratify the code), so L0 enforces separation of powers (#15). |
| 12 | Two projections: `pack` (agent), `site` (human). Both generated, never hand-edited. |
| 13 | Defer task-tracking/Kanban — later view over frontmatter. Don't reimplement git or Linear. |
| 14 | **Vault is in-repo `.brief/` by default** (doc+code atomic, one PR, native governance review). Separate-vault + `.brief.lock` pins is the opt-in for multi-repo only. |
| 15 | **Separation of powers: ratified decisions are READ-ONLY to the coding loop.** A coding commit may not modify a locked decision; the party being checked cannot edit the check. Changing a decision is an **amendment** (L1 advice + L3 human ratification), not a coding side-effect. |
| 16 | **Decision firmness:** `draft` (freely editable while forming) → `active`/`ratified` (locked; amendment-only) → `superseded` (historical). Cheap to change while forming, expensive once committed. |

## Governance stack (the load-bearing mechanism)

Governance presumes defection. The pilot showed the
defection that matters is **not omission** — capable agents *do* keep docs current,
even ungated — but **reversal-by-fiat**: handed write access to "the truth" and told
to keep it current, an agent resolves a conflict between its task and a decision by
*rewriting the decision* to ratify its own code. The fix is **separation of powers**:
the party being checked cannot edit the check.

- **L0 — Procedural (commit hook; mechanical, certain).**
  1. *Read-only decisions* — a coding commit may not modify a locked (`active`/`ratified`) decision. This kills reversal-by-fiat at the root, with no semantic check.
  2. *Conformance assertion* — when governed code changes, the author records `<anchor> conforms: <why>` (code still satisfies the decision) or `<anchor> amend-proposed: <why>` in `.brief/SIGNOFF`.
  3. *Amendment-required* — `amend-proposed` blocks the commit: code needing a decision changed cannot land until that change is ratified.
  4. *Ref integrity* — every `doc://` ref added to code must resolve.
- **L1 — Independent verification (probabilistic).** A fresh-context agent (codex/second Claude) audits *amendment proposals* and samples `conforms` claims — "does this code actually satisfy the decision?" Because the decision is read-only, a `conforms` claim is falsifiable against a *fixed* target. Runs on amendments + sampling, not every commit.
- **L2 — Conformance tests (mechanical, certain — strongest layer).** A decision linking acceptance tests (`test://`) cannot be violated without red CI. Zero agent honesty required.
- **L3 — Human ratification.** The authority that turns an amendment into a new `active` decision; the coding loop cannot self-grant it.

L0's read-only rule is the cheap mechanical root-fix; the expensive semantic checks
(L1/L2) run at the rare amendment, not on every commit.

## Amendment workflow (how a ratified decision changes)

A coding agent that cannot finish without changing a locked decision does **not** edit
it. It writes `.brief/amendments/<anchor>.md` (what should change + why), records
`<anchor> amend-proposed:` in SIGNOFF, and stops — the code is blocked until L3 ratifies
the amendment (with L1 advice). Only then does the decision move to a new revision and
the code land. Develop *to* the decision; change the decision through ratification.

## Doc-first ordering (the teeth)

Code citing a decision must *match* an existing decision. It cannot outrun its spec by
rewriting the spec inline — a needed decision change goes through the amendment workflow
above (ratify first, then land the code). This is what makes "develop to docs" real
rather than "patch the doc afterward."

## Governed-surface scoping (the boundary)

Not all code is decision-bearing; most is mechanical implementation. Requiring a
decision doc for every utility function would be deadening bureaucracy that agents
route around. The **governed surface** is defined explicitly by anchored sections +
their `related_code` globs / `code_links`. Everything outside it is just
implementation, ungoverned. Nailing this boundary (what counts as a "decision" vs
"just code") is a primary design problem.

## Versioning

- Per-doc independent, zero-padded monotonic revision (`v0001.md`, `v0002.md`, …). No global vault version. Agent only bumps the doc it touched.
- Revision assigned at `brief publish`; concurrent publishes resolve by optimistic concurrency (git push conflict → retry next integer).
- `latest` alias = highest revision, machine-maintained. `current` = the live `<doc-id>.md`.
- Significance computed from anchor-hash diffs on demand (`brief diff`, stale warnings) — never encoded in the id.
- Code change → lineage entry always; new revision only on doc content change.

## Anchors

- Explicit only: `<!-- brief:anchor example-anchor -->` applies to the next heading + body. kebab-case, stable; an anchor is a *promise* that the section is a citable API.
- Lint suggests anchors where code points at an un-anchored section; never auto-creates.
- OPEN: anchor deprecation/alias/migration workflow (raised in review; needed before "never rename" is livable).

## Stale detection

- Each anchor body is sha256-hashed per revision.
- Resolving `@0005#x` while a newer revision exists: compare hash of `#x` across revisions. Equal → not stale (decision unchanged). Different → "changed in v0007, review." Anchor-precise, no LLM.

## Filesystem layout

**Default: in-repo `.brief/`** — the code repo *is* the project. Doc + code + frozen
versions move in one commit / one PR; governance review is native. Everything except
the derived index is committed.

```
my-repo/                         (the code repo = the project; git = source of truth)
  .brief/
    project.yaml                 (id, title, context_policy)
    aliases.yaml                 (per-doc latest/stable; machine-maintained)
    links.yaml                   (sidecar: files/symbols/tests → doc refs)
    docs/
      ROADMAP.md                 (the live doc — mutable; was "current.md")
      ROADMAP/
        versions/vNNNN.md        (frozen cache; committed; hash-locked, derived-from-git)
        lineage.yaml             (append-only: commit/run_ref/why/sign-offs)
    brief.sqlite                 (derived index; gitignored)
  src/...
```

**Opt-in: separate vault repo** — for genuine multi-repo projects. A dedicated docs
repo holds `projects/<name>/...`; each code repo commits a `.brief.lock`
(`vault@<git-sha>` + referenced revisions) and the L0 gate verifies refs resolve
against the pinned SHA. Referential integrity without cross-repo atomicity — the
dependency-pinning model. The lockfile dance exists only here; single-repo projects
never see it.

## SQLite schema (derived; summary)

Tables: `projects`, `docs`, `doc_versions`, `anchors` (start/end line, hash, summary, body), `aliases`, `relations` (generic src/rel/dst), `code_links` (file/symbol → doc_ref, source, confidence), `lineage` (doc, revision, commit, run_ref, why, sign-off, ts), plus `anchors_fts` (FTS5, porter). Every field is source-derived or deterministic; `rm brief.sqlite && brief index` fully reconstructs.

## Interface — mechanism in code, policy in prose

The behavior layer (AGENTS.md + skills) does the heavy lifting; the CLI is a small set of
deterministic primitives an *agent* calls, not an app a *human* operates. The pilot
validated this: the AGENTS.md convention alone drove correct behavior with the gate off.

**Mechanical primitives** (must be deterministic → code; few, stable, `--json`):
- `brief resolve <ref>` — ref → file, anchor lines, body, hash. The one verb agents call day-to-day.
- `brief check` — the L0 gate. The agent runs it before committing (local self-check); CI runs `brief check --base` on PRs as the enforcement backstop. A local pre-commit hook is **opt-in**, not default.
- `brief init` — scaffold `.brief/` + inject the AGENTS convention. **Hook-free by default** (`--ci` writes the PR workflow, `--with-skills` installs skills, `--hook` adds the opt-in local hook).
- `brief publish` / `brief ratify` — thin: mint a revision / turn a ratified amendment into a new revision (needs versioning; nucleus).
- Later, only if proven needed: `pack`, `index`/`search`, `site`, `lint`.

**Behavior layer** (policy/workflow → prose; the heavy lifting):
- **AGENTS.md convention** — the always-on *floor*: read-only decisions, conforms/amend-proposed, resolve-don't-guess. Self-sufficient with zero skills, any harness. Injected by `brief init`. (`src/brief/templates.py`)
- **Skills** (accelerants, on-demand): `brief-author-decision`, `brief-amend`, `brief-review` (L1 verifier as a skill that spawns a fresh auditor). (`skills/`)

**Governance layers map onto this, not onto the CLI:** L0 = the mechanical `check` (agent self-runs locally; **CI enforces** on PRs — not a local hook); **L1 = the `brief-review` skill** (spawn a verifier, no binary); L2 = the host project's own tests (`test://`); L3 = human judgment + the thin `ratify` primitive. Only L0 must be code; only CI must enforce it.

The CLI is optimized for machine invocation; humans touch `init` once and `ratify`
occasionally, otherwise reading `.brief/docs/*.md` directly (plain markdown) or a later `site`.

## Stack

Python 3.12+, uv, Typer, rich (lazy-loaded), PyYAML, sqlite3, pydantic, pytest.

## Remaining kills — resolved (recommended; pending final confirm except vault)

- **Vault location → RESOLVED:** in-repo `.brief/` default; separate-vault + `.brief.lock` opt-in for multi-repo. (See decision #14 + layout.)
- **Prompt/run nodes → kill as managed nodes for MVP;** keep opaque `run_ref` pointer in lineage so provenance survives.
- **FTS vs vectors → keep FTS for MVP;** cold-start is retrieval-*easy* (few docs → pack/list all); explicit graph is the primary path; instrument recall and add sqlite-vec later only if the measured middle regime hurts.
- **Sequence → invert:** run the governance experiment FIRST — thin resolver + L0 gate + few docs, measure whether guardrails *catch defection* (not whether agents are honest), before building index/publish/pack/site.
