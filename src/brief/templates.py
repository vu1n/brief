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
- If `brief check` asks for a sign-off (only decisions marked `signoff: required` do, and
  only when you touch the code under their `// Context:` comment) and your change STILL
  satisfies the decision, record `<anchor-id> conforms: <reason>` in `.brief/SIGNOFF`.
  `brief triage` (optional System One model) writes that line itself for the asks it
  rates as clearly conforming; read and answer the ones it leaves.
- If the task CANNOT be done without changing a ratified decision, you may NOT change it
  yourself. Write `.brief/amendments/<anchor-id>.md` (what should change and why), record
  `<anchor-id> amend-proposed: <reason>` in `.brief/SIGNOFF`, and STOP — it needs human
  ratification before code can land. Never bypass the commit hook.
- At each site that embodies a decision, leave a one-line comment:
  `// Context: doc://<project>/<doc-id>@latest#<anchor> — <the rule, in one line>`.
  The ref makes it checkable; the one-line rule puts the constraint in front of the next
  agent exactly where it touches the code. Keep the full reasoning in the decision doc.
- If your memory, notes, or habits disagree with an active decision, the decision wins:
  it is versioned and reviewed with the code, memory is not. Follow the decision and say
  which memory looked stale.

If the repo has a feature map (a `.brief/docs` doc with `type: features`), run
`brief features <files>` before changing code and read the Gotchas of each feature you
touch. When you move or delete code, update that feature's `paths:` in the same change;
when you hit a trap the next agent would hit too, add it to the feature's Gotchas.

**Before committing, run `brief check`** (resolve anything it flags) and `brief pin`
(freeze any `@latest`/`@current` refs you wrote to a concrete revision). CI runs the same
check on PRs — that is the backstop; don't bypass it.

**After authoring/publishing a decision — or before opening a PR — run `brief doctor`**
and close what it flags (wire a `// Context:` ref into governed code, pin a floating ref,
publish a draft you now rely on, re-verify a ref the latest revision made stale). It is
advisory, not a gate: it exists so *you* catch latent drift instead of leaving it for a
human to notice later.
"""

from . import __version__

# Installed from a pinned tag, never from PyPI: `brief` on PyPI is an unrelated package, and
# an unpinned source would let any push to brief's main change every governed repo's gate.
BRIEF_REPO = "https://github.com/vu1n/brief"
BRIEF_SOURCE = f"git+{BRIEF_REPO}@v{__version__}"
CI_MARKER = "# Managed by `brief init --ci`: re-running it rewrites this file. Delete this line to own it."

CI_WORKFLOW = f"""\
{CI_MARKER}
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
        # pinned; upgrade by re-running `brief init --ci` from a newer brief
        run: uvx --from {BRIEF_SOURCE} brief check --base "origin/${{{{ github.base_ref }}}}"
      - name: brief doctor (advisory — latent drift; does not block)
        if: always()   # surface drift even when the gate blocks, for the human PR view
        run: uvx --from {BRIEF_SOURCE} brief doctor --repo .
      - name: brief update check (advisory)
        if: always()
        run: |
          latest=$(git ls-remote --tags --refs {BRIEF_REPO} 'v*' | sed 's|.*refs/tags/||' | grep -E '^v[0-9]+\\.[0-9]+\\.[0-9]+$' | sort -V | tail -1)
          if [ -n "$latest" ] && [ "$latest" != "v{__version__}" ] \\
             && [ "$(printf '%s\\n' v{__version__} "$latest" | sort -V | tail -1)" = "$latest" ]; then
            echo "::notice title=brief $latest is available (this repo pins v{__version__})::Read {BRIEF_REPO}/blob/$latest/UPGRADING.md for what to do, then run: uvx --from git+{BRIEF_REPO}@$latest brief init --ci --with-skills, and commit."
          fi
"""

