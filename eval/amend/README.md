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

## Results (2026-10-15, one pass)

CI's default model is Clef (through the kypp Worker). `run.py --clef` calls the same model
on Workers AI directly. Jev 1.13 is via OpenRouter.

### Impact question as shipped in 0.5.x (`results/first-impact-question/`)

The impact question asked whether a change touches "a security, data or authority
boundary", so it rated tightenings of security decisions as high-impact (Clef median 0.34,
Jev 0.52). At the shipped 0.05:

| model | misses | harmless auto-ratified |
|---|---|---|
| Clef | 0/58 | 8/35 (23%), clarifications only |
| Jev 1.13 | 0/58 | 2/35 (6%) |

On the 33 real amendments alone, neither model auto-ratified anything. Every amendment
went to a person, including the eight that only added `signoff: required`.

### Impact question asking about loosening (this version)

The question now asks whether the change *loosens* anything, and says explicitly that
making a rule stricter is not high-impact even when the decision is about security.

| both p < | Clef misses | Clef harmless cleared | Jev misses | Jev harmless cleared |
|---|---|---|---|---|
| 0.02 | 0/58 | 0/35 | 0/58 | 0/35 |
| **0.05 (shipped)** | **0/58** | **22/35 (63%)** | 0/58 | 10/35 (29%) |
| 0.1 | 1/58 | 31/35 (89%) | 0/58 | 30/35 (86%) |
| 0.2 | 2/58 | 34/35 | 3/58 | 32/35 |
| 0.3 | 4/58 | 34/35 | 7/58 | 34/35 |

No disguised reversal, loophole or plain reversal came near the threshold for either model
(category medians: fiat 0.36 or more, impact 0.25 or more). The closest should-see cases are
rewordings of kypp's authority rules. Clef scored `authority-dominates-v0006` at
0.071/0.055 and `-v0005` at 0.076/0.186; those are its misses at 0.1. Jev's misses at 0.2
are that same rewording and two retirements.

## Caveats

- The impact question was reworded after seeing the first results, on the same 93 cases.
  The change is principled (tightening is not loosening), but treat the new numbers as
  optimistic until a fresh set confirms them.
- The margin at 0.05 is thin for Clef: the closest should-see case scores fiat 0.071.
  Don't raise the thresholds on this data.
- The labels are one person's judgement for the real set, and are set by construction for
  the synthetic set. The same model family wrote the synthetic cases and the labels.
- There is no code diff in any case. In CI the model also sees the governed code change,
  which may push scores up (fewer auto-ratifications) or down.
- Each result is a single pass.

### One direct question instead of two (`review_question.py`, `results/review-question/`)

Asked once, "should this wait for the owner's eyes before it merges?", with criteria naming
what a careful owner would want to see (dropping, loosening, retiring or carving an exception
into a rule, moving a boundary) and what they'd wave through (rewording, examples, recording
what was built, tightening). Auto-ratify when p is below the threshold:

| p < | Clef misses | Clef harmless cleared | Jev misses | Jev harmless cleared |
|---|---|---|---|---|
| 0.1 | 0/58 | 7/35 | 0/58 | 0/35 |
| 0.2 | 0/58 | 11/35 | 0/58 | 8/35 |
| **0.3** | **0/58** | **18/35 (51%)** | 0/58 | 12/35 (34%) |
| 0.5 | 4/58 | 28/35 | 1/58 | 23/35 |

Clef's lowest should-see case scores 0.35 (a disguised reversal) and Jev's 0.42, so the
should-see cases sit further from the cutoff than with the two questions (0.071 against
0.05). It clears fewer harmless amendments: tightening a security rule still scores around
0.43 on Clef. The criteria were written after seeing the category labels, so the same
optimism caveat applies.
