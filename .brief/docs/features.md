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
needs-conformance, amendment-required, broken-ref, and empty-glob for the feature map.

### Gotchas
- Locked status is read from the baseline tree and `changed_files` uses `--no-renames`;
  both close known ways to reverse a locked decision (brief#1). Don't "simplify" them.
- A change that only adds doc-ref comment lines is exempt from needs-conformance; any
  removal or non-ref line re-arms it.
- `features.py` imports `gate.glob_match`, so the gate imports `features` lazily.

<!-- brief:anchor ratify -->
## Ratification

```yaml
paths:
  - "src/brief/ratify.py"
```

The authorized way a locked decision changes: publish a new revision and archive the
amendment stamped `ratified_rev`.

### Gotchas
- The gate only exempts a locked edit that carries the full ratify output (new archive
  entry plus a new version equal to the live doc). A partial hand-made set is blocked.

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

<!-- brief:anchor eval -->
## Eval

```yaml
paths:
  - "eval/**"
```

The memory vs in-repo docs vs Brief experiment (brief#2) and its results.
