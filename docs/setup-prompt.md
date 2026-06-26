# Set up brief — copy/paste prompt

Paste everything in the block below into your coding agent (Claude Code, etc.), running from
the root of the repository you want to govern.

---

```text
Set up `brief` (doc-driven-development governance) in this repository, then help me capture
my first decisions.

1. Install the CLI and verify it:
   uv tool install git+https://github.com/vu1n/brief
   brief --help

2. Initialize:
   brief init --with-skills --ci
   This scaffolds `.brief/`, injects a "Context Vault" convention into AGENTS.md, installs
   brief's skills into `.claude/skills/`, and adds a CI workflow that enforces governance on
   PRs. Read the injected convention before continuing.

3. Capture decisions. Survey this codebase for 3-5 load-bearing architectural decisions or
   invariants — ownership rules, a routing/topology choice, a key contract, a security or
   isolation boundary — the kind worth an ADR. Using the `brief-author-decision` skill, write
   each as `.brief/docs/<id>.md`: frontmatter (`status: active`, plus `related_code` globs
   scoping the code it governs), a stable `<!-- brief:anchor <id> -->`, and the invariant
   stated as the *why* (not the what). Then publish each:
   brief publish <id>

4. Wire code to decisions. In the governed source, add a short reference comment where the
   decision is embodied:
   // Context: doc://<project>/<doc-id>@latest#<anchor>
   Then freeze the refs:
   brief pin

5. Confirm and show me: resolve one ref and summarize the decisions you captured:
   brief resolve 'doc://<project>/<doc-id>@latest#<anchor>'

From now on, follow the convention in AGENTS.md:
- Decisions with `status: active` are READ-ONLY to coding work — never edit one to make your
  change fit; your code conforms to the decision, not the reverse.
- When you change governed code that STILL satisfies a decision, record
  `<anchor> conforms: <why>` in `.brief/SIGNOFF`.
- If a task can't be done without changing a ratified decision, write
  `.brief/amendments/<anchor>.md` (what should change + why), record
  `<anchor> amend-proposed: <why>` in `.brief/SIGNOFF`, and STOP — I will ratify it.
- Run `brief check` and `brief pin` before committing. Never bypass the gate.
```
