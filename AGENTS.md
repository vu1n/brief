# AGENTS.md — working on brief

`brief` is a doc-driven-development governance tool (see [README.md](README.md)). This file
orients an agent contributing to *this codebase*. (For how an agent operates inside a repo
that brief governs, see the convention in `src/brief/templates.py`.)

## What it is

A small Python CLI + library. Decisions are markdown; the CLI is a handful of deterministic
primitives (resolve, gate, publish, ratify, pin); the real product surface is the **behavior
layer** — the convention in `src/brief/templates.py` and the skills in `skills/`.

**Design principle to preserve:** *mechanism in code, policy in prose, enforcement in code.*
Keep the CLI to deterministic primitives an agent calls. Put workflow and judgment in the
convention + skills. The only thing that must be mechanical is the gate.

## Module map (`src/brief/`)

| File | Role |
|------|------|
| `refs.py` | parse/format `doc://` refs |
| `docs.py` | parse `.brief/docs` — frontmatter, `<!-- brief:anchor -->`, `related_code`, body hashes |
| `resolve.py` | ref → file/anchor across revisions; stale-by-anchor-hash |
| `versions.py` | `publish` frozen `vNNNN` snapshots + `aliases.yaml` (`latest`) |
| `gate.py` | the L0 gate (separation of powers): `check(repo, brief_dir, base=None)` |
| `doctor.py` | advisory lint (repo-wide): latent drift the gate doesn't block — unwired / unpublished / unpinned / stale refs. Machine-first `Report`, `--strict` opt-in |
| `ratify.py` | the authorized decision change (publish new revision + archive amendment) |
| `features.py` | feature map: `type: features` docs → features (anchor + `paths:` globs); diff → features; dead-glob detection for the gate |
| `pin.py` | rewrite `@latest`/`@current` → concrete revision in code |
| `scan.py` | `brief backfill` scanner: inventory docs (genre/status/tracked) + code signals + module tree into a context map |
| `s1.py` | optional System One client over the TypeSafe SDK (Jev/Clef): typed questions → calibrated probabilities, for triage only; None = no opinion |
| `init.py` / `templates.py` | `brief init` + the injected convention / CI workflow |
| `gitutil.py` | minimal git plumbing (staged + range modes) |
| `cli.py` | Typer entrypoint |

`skills/` — the agent-facing skills (`brief-author-decision`, `brief-amend`, `brief-review`,
`brief-backfill`, `brief-feature-map`).
`.brief/docs/features.md` — brief's own feature map; read the Gotchas for the area you touch.
`docs/DESIGN.md` — design of record.

## Dev

```sh
uv venv && uv pip install -e ".[dev]"
uv run pytest -q            # the suite — tests/
uv run brief --help
```

## Conventions

- **Contract-first.** The parse/ref/gate functions are the boundary; tests target the
  boundary (`tests/test_thin.py`), not the implementation.
- **Keep the CLI thin.** Resist adding human-ergonomic CLI affordances; the agent calls
  primitives and the prose layer carries the rest.
- **Enforcement is mechanical; everything advisory is prose.** Don't move the gate into a
  skill, and don't move authoring judgment into the CLI.
- **Protect the core property.** The design was proven adversarially: separation of powers
  (decisions read-only to the coding loop) eliminates reversal-by-fiat. Don't let a change
  erode it.

## The governance model (the domain you're building)

Decisions in `.brief/docs/` are ratified constraints, **read-only to the coding loop**. Code
conforms (or, for a `signoff: required` decision whose `// Context:` block changed, the
author records `<anchor> conforms:` / proposes an amendment and stops). Sign-off is opt-in
because sign-offs on every governed edit get rubber-stamped; read-only is the real guard.
L0 (`check`) is mechanical and runs locally + in CI; L1 is the `brief-review` skill; L2 is
the host project's tests; L3 is a human running `ratify`. Reversal-by-fiat (rewriting a
decision to ratify your own code) is the failure the whole design exists to prevent.

## Dogfood TODO

brief maps itself (`.brief/docs/features.md`, kept honest by a test) but does not yet
govern itself with decisions. A natural next step: author brief's own load-bearing
decisions (e.g. *mechanism-in-code/policy-in-prose*, *separation-of-powers: decisions
read-only*) as `.brief/docs/` and govern this repo with brief.
