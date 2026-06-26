"""Canonical text injected by `brief init` — the always-on governance floor.

This is the *behavior layer*: short, self-sufficient (works with zero skills, any
harness), and the thing the pilot proved does the heavy lifting. Keep it tight.
"""

MARKER = "## Context Vault (brief)"

AGENTS_SNIPPET = """\
## Context Vault (brief)

Architectural decisions live in `.brief/docs/` as governance docs. Each has a stable
anchor (`<!-- brief:anchor id -->`), a `status`, and the code it governs (`related_code`
globs). A decision is addressable as `doc://<project>/<doc-id>@latest#<anchor>` — resolve
one with `brief resolve <ref>` to read the exact decision; don't infer it from the ref.

Decisions are **ratified constraints, not editable notes**. Develop *to* them:

- A decision with `status: active` is READ-ONLY to coding work. Do NOT edit it to make
  your change fit — your code conforms to the decision, not the reverse.
- When you change code a decision governs and it STILL satisfies that decision, record
  `<anchor-id> conforms: <reason>` in `.brief/SIGNOFF`.
- If the task CANNOT be done without changing a ratified decision, you may NOT change it
  yourself. Write `.brief/amendments/<anchor-id>.md` (what should change and why), record
  `<anchor-id> amend-proposed: <reason>` in `.brief/SIGNOFF`, and STOP — it needs human
  ratification before code can land. Never bypass the commit hook.
- Prefer a short `// Context: doc://...#anchor` ref over re-explaining a decision in code.

**Before committing, run `brief check`** (resolve anything it flags) and `brief pin`
(freeze any `@latest`/`@current` refs you wrote to a concrete revision). CI runs the same
check on PRs — that is the backstop; don't bypass it.
"""

CI_WORKFLOW = """\
name: brief
on: pull_request
jobs:
  govern:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # need the base ref for the range check
      - uses: astral-sh/setup-uv@v5
      - name: brief governance gate
        # once brief is published: `uvx brief check ...`; until then install from source.
        run: uvx brief check --base "origin/${{ github.base_ref }}"
"""

