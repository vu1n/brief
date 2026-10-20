# Eval: does a model earn a place in `brief evidence`?

`brief evidence` shows the reviewer of an amendment what changed and what else it touches.
Most of that is exact without a model: the decision edit is a diff (removed and added lines
by number, qualifier words that left or entered), the amendment has template headings, and
governed scope is two lists of globs. Two places looked like they might need one:

1. **Pulling the rule, exceptions, reason and assumptions out of decision prose**
   (Clairic, Cloudflare's extraction model), so a reviewer sees the qualifiers an edit drops.
2. **Finding other decisions an edit undermines** when nothing links them (Clef), since refs
   and shared governed files miss decisions that share a premise but not a file.

Both were run once, live, on Workers AI, 2026-10-20. Neither feeds anything that decides.

## 1. Clairic on real decision text: no role

`run.py clairic --pillbox ../pillbox --kypp ../kypp` sends each of the 39 live decision
anchors in pillbox and kypp with four fields: `rule` and `reason` (text), `exceptions` and
`assumptions` (lists).

| field | result |
|---|---|
| `rule` | 39/39 answered, every span matches the source, but only 8/39 are a whole sentence (median 8 words; e.g. "never to embed the optimizer", "PTY-free") |
| `reason` | 39/39 answered, spans valid, 11/39 a whole sentence |
| `exceptions` | 387 items, 322 of them 3 words or fewer ("The", "Dr", "two of the"); 11/39 answers return a different number of spans than values; list confidence ~1e-30 |
| `assumptions` | 355 items, 296 of them 3 words or fewer; 12/39 span/value mismatches |
| exceptions found | of the 12 sentences with an explicit exception word (except, unless, only if...), Clairic returned a usable item inside 1 |

Latency was fine (median 0.40 s, 94k input tokens in all). The problem is the output: valid
spans that clip the decisive clause, and list fields that are mostly fragments. For an
amendment the line diff already shows every qualifier that changed, exactly, and the
decision's own `##` heading is a better one-line summary than the `rule` span. So
`brief evidence` does not call Clairic. Worth re-testing if its list fields improve, or for
scanned/image inputs, which this eval did not cover.

## 2. Clef ranking other decisions: a shadow role

`cases.json` holds 14 edits to real pillbox decisions (one line replaced each): 9 that break
something another decision relies on (the guest gets the real token; egress passes through
by default; a resident daemon owns seq; raw PTY bytes are persisted...), 4 harmless (a
reword, a tightening, a new adapter in a list), and 1 that is locally risky but labeled
with no cross-decision impact. For each, the affected decisions were labeled by hand (16
pairs). `run.py impact --pillbox ../pillbox` asks Clef `evidence.impact_question()` for every
edit against each of the 24 other decisions (336 calls) and compares with what
`brief evidence` links without a model.

| what the reviewer is shown | decisions listed | affected found | model additions on the 5 edits with no labeled impact |
|---|---|---|---|
| links only (refs + shared files) | 36 | 9/16 | n/a |
| links + Clef top 2 unlinked at p>=0.5 | 47 | 13/16 | 0 |
| **links + Clef top 3 unlinked at p>=0.5** (shipped) | 52 | 13/16 | 0 |
| links + Clef top 5 unlinked at p>=0.3 | 78 | 15/16 | 1 |

Links alone miss 7 of 16: shared files are mostly hub files (`src/sandbox/mod.rs` links
`adr-001` to 8 decisions), and a premise like "the guest only ever holds stubs" lives in
`adr-004-vault-broker-oauth`, which shares no file with the edit that breaks it. Clef's
additions recovered 4 of those at the cost of 16 more lines to read, and added nothing to
the harmless edits (their highest p was 0.15). Median latency 0.38 s per call; one
amendment costs one call per other decision. A second run of the same 336 calls moved
individual scores by a few hundredths and one cutoff row by one decision.

## What this does not show

- **One author** wrote the edits, the labels and the question, on the same cases the
  thresholds were picked from. This is development evidence, not a benchmark; the 3/0.5
  setting may not hold on another repo.
- **Small:** 14 edits in one repo. The kypp decisions were used only for Clairic.
- **Not safety:** a model link is a prompt to look, never a finding. Missing answers are
  reported as "not checked". No threshold here touches what merges.
- **No reviewer study:** "decisions listed" stands in for reviewer effort.

## Demo

`demo.py ../pillbox [--clef]` clones pillbox to a temp dir and prints `brief evidence` for
(1) the real v0002 to v0003 amendment of `managed-tier-do-gateway` that Vu ratified, and
(2) an amendment framed as "clarify, no behaviour change, tests pass" that starts persisting
raw PTY bytes, drops `src/attach/pump.rs` from the decision's scope and edits that file. The
view shows the dropped `never`, both unverified claims, the missing sections, and the edited
file leaving governance; Clef adds `agent-io-pty-free-contract`, `session-event-log-spine` and
`dx-zero-config-local` as model-inferred.

On that second amendment `brief triage --amendments` (Clef) rates p=0.09 and calls it
auto-ratifiable: it builds the code diff from the *proposed* globs, so it never sees
`pump.rs`. With the fix from brief#18 (triage selects code by the globs before *and*
after the edit) the same amendment rates 0.36 and escalates. That margin over the 0.3
cutoff is thin; a deterministic rule that any narrowing escalates would not depend on it.
