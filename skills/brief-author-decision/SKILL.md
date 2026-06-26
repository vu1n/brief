---
name: brief-author-decision
description: Write or scope a brief governance decision doc in .brief/docs/. Use when capturing an architectural decision or invariant as a governed constraint — defining its anchor, the code it governs, and the invariant code must conform to. Invoke for "add a decision", "write an ADR in brief", "govern this invariant".
---

# Authoring a brief decision

A decision doc records *why* — a constraint code must conform to — not *what* the code
does. One decision per file, one anchor per decision.

## File: `.brief/docs/<doc-id>.md`

```md
---
id: <doc-id>            # kebab, stable; e.g. adr-007-session-ownership
project: <project>
type: decision
status: active          # draft = freely editable while forming; active/ratified = LOCKED
title: <one line>
related_code:           # the governed surface — globs, not every file
  - "src/session/**"
  - "src/gateway.rs"
---

<!-- brief:anchor <anchor-id> -->
## <imperative statement of the decision>

<1–3 sentences: the decision / invariant.>

**Why.** <the reason — the durable value; code can't reconstruct intent cheaply.>

### Invariant
- <a checkable statement code must satisfy>
- <prefer invariants a test could later enforce (L2)>
```

## Rules

- **The anchor is a promise.** kebab-case, stable, never renamed after code references it.
  It is the citable API — pick it deliberately.
- **Scope `related_code` to the governed surface**, not the whole repo. Over-scoping trips
  the gate on every commit; under-scoping leaves the decision unenforced. Glob the files
  that actually embody the decision.
- **Write the invariant to be conformance-checkable.** "Every event carries an actor" beats
  "actors matter." A good invariant can later get a `test://` link (L2 enforcement).
- **Firmness:** start `draft` while forming (freely editable); promote to `active` once the
  team commits — then it is read-only to coding work and only an amendment can change it.
- **One decision per doc.** Overlapping `related_code` across decisions is fine and expected.

## After authoring

Reference it from code with a short `// Context: doc://<project>/<doc-id>@latest#<anchor>`
instead of re-explaining it. The pre-commit gate verifies the ref resolves.
