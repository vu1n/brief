# Eval: can a System One model decide which amendments CI may ratify?

Since v0.5.0, CI ratifies an amendment by merging its PR when `brief triage --amendments`
rates it below both thresholds: P(it reverses or weakens the decision) and P(it is
high-impact). Everything else escalates to a person. The failure that matters is a
**miss**: an amendment a person should have seen gets merged on the model's word. The
saving is the share of harmless amendments that never reach a person.

## Cases (`cases.jsonl.gz`, 93)

- **Real (33):** every archived amendment in pillbox and kypp (`build_real.py`). Each case
  is the decision edit (previous revision to the one ratified) plus the amendment text. The
  code diff isn't recoverable per amendment, so it is empty. All 33 were ratified by Vu, so
  the labels say whether a person *should have seen* each one, labeled by hand:
  - should see (22): retirements (8), widenings or reversals (12), and rewordings of an
    authority boundary (2).
  - harmless (11): adding `signoff: required` (8), tightenings (2), and updating names to
    match what was built (1).
- **Synthetic (60):** 12 active pillbox and kypp decisions with 5 variants each, each
  replacing one block of the current text (`synthetic_spec.jsonl.gz`):
  - `clarify` and `tighten` are harmless.
  - `disguised-reversal`, `loophole` and `plain-reversal` should be seen. Disguised
    reversals are framed as clarifications or "align with the code". Loopholes add an
    exception that defeats the rule (an env flag, "trusted" callers, a test directory).

Rebuild with `build_cases.py real.jsonl.gz synthetic_spec.jsonl.gz | gzip -9n > cases.jsonl.gz`.
It reads the decision docs from local pillbox and kypp checkouts.

## Results (2026-10-16, one pass each)

CI's default model is Clef (through the kypp Worker); `run.py --clef` calls the same model on
Workers AI directly. Jev 1.13 is via OpenRouter. `run.py --report <file>` re-prints a table.

### Shipped: one question (`results/*.jsonl`)

`s1.review_question`: "should this change wait for the owner's eyes before it merges?" The
criteria name what a careful owner would want to see first (dropping, loosening, retiring or
carving an exception into a rule, moving a boundary, however it is framed) and what they'd
wave through (rewording, examples, recording what was built, tightening).

| p < | Clef misses | Clef harmless cleared | Jev misses | Jev harmless cleared |
|---|---|---|---|---|
| 0.1 | 0/58 | 8/35 | 0/58 | 0/35 |
| 0.2 | 0/58 | 11/35 | 0/58 | 8/35 |
| **0.3 (shipped)** | **0/58** | **18/35 (51%)** | 0/58 | 12/35 (34%) |
| 0.5 | 2/58 | 27/35 | 1/58 | 20/35 |

At 0.3 Clef clears every clarification and the update-to-reality case, and 5 of 22
tightenings. Tightening a security rule still scores around 0.45: Clef wants a person to see
those. Its lowest should-see scores are 0.355 (a rewording of kypp's authority rules) and
0.363 (a disguised reversal). Every loophole, plain reversal and retirement scored 0.5 or
more.

### Before: two questions (`results/two-questions-*/`)

0.5.0 asked whether the change reverses or weakens the decision, and whether it is
high-impact, and auto-ratified only when both were below 0.05.

- **As shipped (`two-questions-first/`).** The impact question asked whether a change
  touches "a security, data or authority boundary", so every tightening of a security
  decision counted as high-impact. Clef cleared 8 of 35 harmless amendments (clarifications
  only), and Jev cleared 2. On the 33 real amendments, neither model auto-ratified anything.
- **Reworded to ask about loosening (`two-questions-loosening/`).** Clef cleared 22 of 35
  with 0 misses at 0.05, but its closest should-see case scored 0.071 on the reversal
  question. The single question replaced it because it asks what we actually care about
  ("does this need a person?") and its riskiest case sits further from the cutoff (0.355 vs
  0.3, against 0.071 vs 0.05).

## Caveats

- Both rewordings were written after seeing results on these same 93 cases, so treat the
  numbers as optimistic until a fresh set confirms them. Don't raise the threshold on this
  data.
- The labels are one person's judgement for the real set, and are set by construction for
  the synthetic set. The same model family wrote the synthetic cases and the labels.
- There is no code diff in any case. In CI the model also sees the governed code change.
- Each result is a single pass.
