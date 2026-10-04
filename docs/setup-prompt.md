# Move a repo onto brief: copy/paste prompt

Paste the block below into your coding agent (Claude Code, Codex, etc.) from the root of the
repo you want to govern. It works for a fresh repo and for one that already has ADRs, a
decisions log, design docs, or rationale comments. In the second case it migrates them
instead of starting over. It ends with a PR for you to review. The decisions it marks
`active` become read-only to agents once merged, so that review is your ratification.

---

```text
Move this repository onto `brief` (doc-driven-development governance): capture its
load-bearing decisions as governed docs, wire them to the code, and open a PR for my review.
I'm not available for questions mid-way; where you can't verify something, mark it draft and
list it in the PR instead of guessing.

1. Install and initialize (brief is not on PyPI; the PyPI package named `brief` is
   unrelated):
     uv tool install git+https://github.com/vu1n/brief@v0.4.0
     brief init --with-skills --ci
   This scaffolds `.brief/`, injects the governance convention into AGENTS.md (or
   CLAUDE.md), installs the brief skills into `.claude/skills/`, and adds a pinned CI gate.
   The skills are slash-only (`/brief-backfill` etc.), so read their SKILL.md files directly
   when a step below points at one.
   If the convention was already present, `init` refreshes it to the current text. Read the
   convention before continuing; it applies to you from here on.

2. Map what already exists:
     brief backfill          # writes .brief/backfill/map.md
   Read the map: existing decision docs (ADRs, design docs, decisions logs), rationale
   comments in code, and existing doc:// refs.

3. Capture decisions. Follow `.claude/skills/brief-backfill/SKILL.md` if the map found
   existing decision docs or rationale comments; otherwise survey the code yourself. Either way:
   - Ratify a decision only if a capable agent reading the code would plausibly get it wrong
     AND the mistake would be costly or hard to undo: ownership and isolation boundaries,
     key contracts and formats, "we removed X, don't bring it back", and conventions the
     code alone doesn't reveal (rounding, logging/PII, retry policy, config sources).
     Expect roughly 5-10. Everything else is a one-line why-comment at the code (and a
     Gotcha in the feature map if there is one), not a decision: too many decisions train
     everyone to rubber-stamp them.
   - Mark `signoff: required` only on the few where silent drift is dangerous (security
     boundaries, data loss, money). Every active decision is read-only either way.
   - Verify every claim against current code before marking it `status: active`. Anything
     you can't confirm stays `status: draft`.
   - Write each as `.brief/docs/<id>.md` per `.claude/skills/brief-author-decision/SKILL.md`,
     then `brief publish <id>`.
   - If the repo keeps another decisions log (e.g. docs/decisions.md, an ADR folder), don't
     leave two sources of truth: carry each live entry into .brief/docs/, mark superseded
     ones superseded, and turn the old log into a short pointer to `.brief/docs/`.

4. Wire decisions to code. At each site that embodies a decision, add one line:
     // Context: doc://<project>/<doc-id>@latest#<anchor> — <the rule, in one line>
   (use the file's comment syntax). Put it where an agent editing that code will see it.
   Then: brief pin

5. Check your work:
     brief check --base origin/<default-branch>
     brief doctor
   Close everything doctor flags (unwired, unpublished, unpinned).

6. Commit on a branch and open a PR. In the description, list:
   - decisions captured: id, one-line rule, and the code each governs
   - decisions carried forward, re-grounded, or superseded from existing docs, and what
     drift you found
   - drafts that need my judgment
   - anything in agent memory files or notes in this repo that contradicts a decision
     (flag it; the decision wins)
```

---

After merging, agents working in the repo follow the injected convention:
- Active decisions are read-only.
- A change under a `signoff: required` decision's `// Context:` comment records
  `<anchor> conforms: <why>` in `.brief/SIGNOFF`.
- A change that needs a decision changed writes an amendment and stops for you to run
  `brief ratify`.

To upgrade: brief's CI posts a notice on PRs when a newer brief release exists. Run the command
it gives (`uvx --from git+https://github.com/vu1n/brief@<new tag> brief init --ci --with-skills`)
and commit the result. That refreshes the convention, the skills, and the pinned workflow. A
`brief.yml` without the "Managed by `brief init --ci`" line is left alone, so bump its tag by
hand.
