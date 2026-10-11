---
name: brief-amend
description: Propose an amendment when a coding task conflicts with a ratified (read-only) brief decision. Use when the gate blocks you with "ratified decision is read-only" or "amendment-required", or when you realize a task cannot be done without changing an active decision. The correct escalation — never edit the decision to make your code pass.
disable-model-invocation: true
---

# Proposing a brief amendment

A ratified (`status: active`) decision is READ-ONLY to coding work. If your task cannot be
done without changing it, you do **not** change it on your own authority and you do **not**
force the code through. You propose an amendment and STOP: merging your PR is the
ratification, and you don't merge it. (Rewriting the decision to
ratify your own code is the one failure this system exists to prevent.)

## When this applies

- The gate blocked your commit with a `ratified-edit` or `amendment-required` message, or
- You can see your task contradicts an active decision's invariant before you start.

## Procedure

1. **Do not edit the decision doc to make code pass**, and `git restore` any conflicting
   code you wrote. You cannot make a change valid by rewriting the constraint it violates.
2. Write `.brief/amendments/<anchor-id>.md`:

   ```md
   # Amendment proposal: <anchor-id>

   **Decision:** doc://<project>/<doc-id>@latest#<anchor-id>
   **Proposed by:** <agent/run>   **Date:** <date>

   ## What should change
   <the new invariant, or the clause to retire — precisely.>

   ## Why
   <the engineering reason the standing decision no longer holds, or the new requirement.>

   ## Code that needs it
   <the change blocked by the current decision; files / sketch.>

   ## Impact / risk
   <what else the decision protects; what breaks if it changes; migration notes.>
   ```
3. Record `<anchor-id> amend-proposed: <one-line reason>` in `.brief/SIGNOFF`.
4. Optionally, put the proposed text in the live decision doc in the same PR. Every anchor
   you change needs its own `.brief/amendments/<anchor>.md`, or CI blocks the edit as
   `ratified-edit`. Never touch `versions/` or run `brief publish`/`brief ratify` yourself.
   Locally `brief check` still blocks this edit (a commit can't ratify); that is expected,
   and if the repo has a pre-commit hook, leave the text out and keep it in the amendment.
5. Commit the amendment + SIGNOFF (+ the proposed text). Never `--no-verify`. Open the PR.
6. **Stop and report** the task is blocked pending ratification. Do not merge, do not keep
   trying to land the code, and do not look for a workaround.

CI reports the PR as `pending-ratification`, and the System One triage (when configured)
rates it `auto-ratifiable` or labels it `needs-ratification`. Merging the PR ratifies it:
CI publishes the new revision and archives your amendment with `ratified_by:` the merger.

**After ratification (pull the bot's commit first), run `brief doctor`.** The new revision changes the anchor's hash, so
every code ref pinned to the *old* revision is now `stale-ref` — the code was written
against a decision that has since moved. doctor lists each one; re-verify the code still
conforms and re-pin (`brief pin`). This is the drift a ratify silently creates, caught
mechanically instead of by a human noticing.
